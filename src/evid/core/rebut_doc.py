import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def rebut_doc(workdir: Path):
    """Generate rebuttal document from evidence directory."""
    try:
        subprocess.run(["fct_csvbib", "label.csv", "-n"], cwd=workdir, check=True)
        # output_path = Path.home() / "Documents/fct_output"
        output_path = workdir
        output_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["fct_rebut", str(workdir / "label_table.bib")], cwd=output_path, check=True
        )
        rebut_tex = output_path / "rebut.tex"
        if rebut_tex.exists():
            subprocess.run(["xdg-open", str(rebut_tex)])
        else:
            logger.warning(f"Rebuttal file {rebut_tex} was not generated")
    except subprocess.CalledProcessError as e:
        raise FileNotFoundError(
            f"Command failed: {e.cmd} with exit code {e.returncode}"
        )
