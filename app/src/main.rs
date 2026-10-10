//! evid in a native window.
//!
//!     evid-app --url URL [--raise-file PATH]   # show a running evid server (what `evid gui` does)
//!     evid-app [EVID ARGS...]                  # start `evid [ARGS] gui --headless` itself, e.g. `evid-app -d ./evid`;
//!                                              # stop it when the window closes (EVID_BIN overrides `evid`)
//!
//! Touching the raise file (a second `evid gui`) brings the window to the front.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{exit, Child, Command};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant, SystemTime};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

/// Desktop-file id. GNOME's app switcher looks up `<id>.desktop` for the icon.
const APP_ID: &str = "io.github.evidlabel.evid";
const ICON_PNG: &[u8] = include_bytes!("../icons/icon.png");

/// Write the icon and a desktop entry so the switcher can find them.
/// GTK's own application id is left unset: registering one makes GTK refuse a
/// second evid-app, and two data dirs are allowed to be open at once.
#[cfg(target_os = "linux")]
fn publish_desktop_entry() -> Option<PathBuf> {
    let base = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local/share")))?;
    let icon = base.join(format!("icons/hicolor/512x512/apps/{APP_ID}.png"));
    let desktop = base.join(format!("applications/{APP_ID}.desktop"));
    std::fs::create_dir_all(icon.parent()?).ok()?;
    std::fs::create_dir_all(desktop.parent()?).ok()?;
    std::fs::write(&icon, ICON_PNG).ok()?;
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("evid-app"));
    let exec = exe.display().to_string().replace('"', "\\\"");
    let text = format!(
        "[Desktop Entry]\n\
         Type=Application\n\
         Name=evid\n\
         Comment=Evidence manager\n\
         Exec=\"{exec}\"\n\
         Icon={icon}\n\
         StartupWMClass={APP_ID}\n\
         Terminal=false\n\
         Categories=Office;\n",
        icon = icon.display(),
    );
    std::fs::write(&desktop, text).ok()?;
    Some(icon)
}

#[cfg(target_os = "linux")]
fn set_switcher_icon(window: &tauri::WebviewWindow, icon: Option<&std::path::Path>) {
    use gtk::prelude::*;

    let Ok(gtk_win) = window.gtk_window() else {
        return;
    };
    if let Some(path) = icon {
        let _ = gtk_win.set_icon_from_file(path);
    }
    // Wayland ignores the window icon. The shell matches this id to the desktop file.
    if gtk_win.display().backend().is_wayland() {
        gtk_win.realize();
        if let Some(gdk_win) = gtk_win.window() {
            let id = std::ffi::CString::new(APP_ID).unwrap();
            unsafe {
                gdk_wayland_window_set_application_id(gdk_win.as_ptr().cast(), id.as_ptr());
            }
        }
    }
}

#[cfg(target_os = "linux")]
extern "C" {
    fn gdk_wayland_window_set_application_id(
        window: *mut std::ffi::c_void,
        application_id: *const std::ffi::c_char,
    );
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8790)
}

fn start_server(bin: &str, args: &[String], port: u16, raise: &PathBuf) -> Child {
    let mut child = Command::new(bin)
        .args(args)
        .args(["gui", "--headless", "-p", &port.to_string()])
        .env("EVID_IN_APP", "1")
        .env("EVID_RAISE_FILE", raise)
        .spawn()
        .unwrap_or_else(|e| {
            eprintln!("evid-app: cannot start {bin}: {e}");
            exit(1)
        });
    let deadline = Instant::now() + Duration::from_secs(30);
    while TcpStream::connect(("127.0.0.1", port)).is_err() {
        if let Ok(Some(status)) = child.try_wait() {
            // e.g. another evid gui already runs for this data dir and was raised instead
            exit(status.code().unwrap_or(1));
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            eprintln!("evid-app: server did not come up on port {port}");
            exit(1);
        }
        sleep(Duration::from_millis(100));
    }
    child
}

fn mtime(p: &PathBuf) -> Option<SystemTime> {
    std::fs::metadata(p).and_then(|m| m.modified()).ok()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let flag = |name: &str| args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned();
    let (url, raise, child) = match flag("--url") {
        Some(url) => (url, flag("--raise-file").map(PathBuf::from), None),
        None => {
            let bin = std::env::var("EVID_BIN").unwrap_or_else(|_| "evid".into());
            let port = free_port();
            let raise = std::env::temp_dir().join(format!("evid-app-{}.raise", std::process::id()));
            let child = start_server(&bin, &args, port, &raise);
            (format!("http://127.0.0.1:{port}/"), Some(raise), Some(child))
        }
    };
    let url = url.parse().unwrap_or_else(|e| {
        eprintln!("evid-app: bad url {url}: {e}");
        exit(2)
    });

    #[cfg(target_os = "linux")]
    let icon = publish_desktop_entry();

    tauri::Builder::default()
        .manage(Server(Mutex::new(child)))
        .setup(move |app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("evid gui")
                .inner_size(1400.0, 900.0)
                .decorations(true)
                .maximized(true)
                .visible(false)
                .build()?;
            #[cfg(target_os = "linux")]
            set_switcher_icon(&window, icon.as_deref());
            // Maximized fills the work area and leaves the title bar. Clear any
            // remembered exclusive fullscreen so the close button stays.
            let _ = window.set_fullscreen(false);
            let _ = window.set_decorations(true);
            let _ = window.maximize();
            let _ = window.show();
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let mut seen = raise.as_ref().and_then(mtime);
                loop {
                    sleep(Duration::from_millis(300));
                    // a second `evid gui` touched the raise file: come to the front
                    if let Some(p) = raise.as_ref() {
                        let now = mtime(p);
                        if now.is_some() && now != seen {
                            seen = now;
                            if let Some(w) = handle.get_webview_window("main") {
                                let _ = w.unminimize();
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                    // when the server we started exits (Ctrl+W / Ctrl+Q in the page), close the window too
                    let state = handle.state::<Server>();
                    let mut guard = state.0.lock().unwrap();
                    if let Some(c) = guard.as_mut() {
                        if !matches!(c.try_wait(), Ok(None)) {
                            guard.take();
                            drop(guard);
                            handle.exit(0);
                            break;
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building evid-app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut c) = app.state::<Server>().0.lock().unwrap().take() {
                    let _ = c.kill();
                    let _ = c.wait();
                }
            }
        });
}
