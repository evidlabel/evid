# evid - pdf labeller

`evid` is a GUI application for labelling text from PDF files, aimed at the legal industry. 
With `evid` you can label snippets and add remarks on read-through, which will then be citable in Typst documents. 

## Key Features

- **PDF Logging**: Add PDFs with metadata such as title, authors, tags, and dates.
- **Automatic Date Extraction**: Extract dates from PDFs using advanced text parsing.
- **PyQt6 GUI**: Intuitive interface with tabs for adding and browsing documents.
- **Typst Integration**: Generate Typst documents for labels and responses, with BibTeX support for citations.
- **Modular Database**: Organize documents into datasets with YAML-based metadata storage.
- **CLI Support**: Manage datasets and evidence through a powerful command-line interface.

## Getting Started
`evid` help exposes the cli structure, paste this into an LLM to formulate workflows on datasets. 
<pre><font color="#26A269"><b>➜</b></font> <font color="#12488B">evid</font> <font color="#2AA1B3">-h</font>
<b>Usage: evid </b><font color="#A2734C"><b>...</b></font><b> </b><font color="#2D2D2D"><b> (--json, -h, --help)</b></font>
<font color="#D0CFCC"><b>Description: evid CLI for managing PDF documents</b></font>
<font color="#228594"><b>evid</b></font><font color="#2D2D2D">──────────────────────────────</font><font color="#B4B4B4"><b>evid CLI for managing PDF documents</b></font>
<font color="#2D2D2D">├── </font><font color="#26A269"><b>config</b></font><font color="#2D2D2D">────────────────────────</font><font color="#B4B4B4"><b>Deal with configuration of evid</b></font>
<font color="#2D2D2D">│   ├── </font><font color="#2AA1B3">show</font><font color="#2D2D2D">──────────────────────</font><font color="#B4B4B4"><b>Show the current config settings and where they are defined</b></font>
<font color="#2D2D2D">│   └── </font><font color="#2AA1B3">update</font><font color="#2D2D2D">────────────────────</font><font color="#B4B4B4"><b>Initialize or update .evidrc with default settings</b></font>
<font color="#2D2D2D">├── </font><font color="#26A269"><b>doc</b></font><font color="#2D2D2D">───────────────────────────</font><font color="#B4B4B4"><b>Manage documents</b></font>
<font color="#2D2D2D">│   ├── </font><font color="#A2734C">--dataset, -s</font><font color="#8B8A88">: str</font><font color="#2D2D2D">────────</font><font color="#A2734C"><i>Dataset name</i></font>
<font color="#2D2D2D">│   ├── </font><font color="#A2734C">--uuid, -u</font><font color="#8B8A88">: str</font><font color="#2D2D2D">───────────</font><font color="#A2734C"><i>UUID of the document</i></font>
<font color="#2D2D2D">│   ├── </font><font color="#2AA1B3">bibtex</font><font color="#2D2D2D">────────────────────</font><font color="#B4B4B4"><b>Generate BibTeX files from label.typ files</b></font>
<font color="#2D2D2D">│   ├── </font><font color="#2AA1B3">label</font><font color="#2D2D2D">─────────────────────</font><font color="#B4B4B4"><b>Label a document in a dataset</b></font>
<font color="#2D2D2D">│   ├── </font><font color="#2AA1B3">list</font><font color="#2D2D2D">──────────────────────</font><font color="#B4B4B4"><b>List documents in the dataset</b></font>
<font color="#2D2D2D">│   └── </font><font color="#2AA1B3">rebut</font><font color="#2D2D2D">─────────────────────</font><font color="#B4B4B4"><b>Generate rebuttal for a document in a dataset</b></font>
<font color="#2D2D2D">├── </font><font color="#2AA1B3">gui</font><font color="#2D2D2D">───────────────────────────</font><font color="#B4B4B4"><b>Launch the evid GUI</b></font>
<font color="#2D2D2D">└── </font><font color="#26A269"><b>set</b></font><font color="#2D2D2D">───────────────────────────</font><font color="#B4B4B4"><b>Manage datasets</b></font>
<font color="#2D2D2D">    ├── </font><font color="#2AA1B3">add</font> <font color="#FFAF00">[SOURCE, str]</font><font color="#2D2D2D">─────────</font><font color="#B4B4B4"><b>Add a PDF from a URL or local file to a dataset</b></font>
<font color="#2D2D2D">    │   ├── </font><font color="#A2734C">--autolabel, -a</font><font color="#8B8A88">: bool</font><font color="#2D2D2D">─</font><font color="#A2734C"><i>Auto-label paragraphs when labelling</i></font>
<font color="#2D2D2D">    │   ├── </font><font color="#A2734C">--label, -l</font><font color="#8B8A88">: bool</font><font color="#2D2D2D">─────</font><font color="#A2734C"><i>Open the labeler after adding the PDF</i></font>
<font color="#2D2D2D">    │   └── </font><font color="#A2734C">--dataset, -s</font><font color="#8B8A88">: str</font><font color="#2D2D2D">────</font><font color="#A2734C"><i>Dataset name or number</i></font>
<font color="#2D2D2D">    ├── </font><font color="#2AA1B3">create</font><font color="#2D2D2D">────────────────────</font><font color="#B4B4B4"><b>Create a new dataset</b></font>
<font color="#2D2D2D">    │   └── </font><font color="#A2734C">--dataset, -s</font><font color="#8B8A88">: str</font><font color="#2D2D2D">────</font><font color="#A2734C"><i>Dataset name or number</i></font>
<font color="#2D2D2D">    ├── </font><font color="#2AA1B3">list</font><font color="#2D2D2D">──────────────────────</font><font color="#B4B4B4"><b>List all available datasets</b></font>
<font color="#2D2D2D">    └── </font><font color="#2AA1B3">track</font><font color="#2D2D2D">─────────────────────</font><font color="#B4B4B4"><b>Track a dataset with Git</b></font>
<font color="#2D2D2D">        └── </font><font color="#A2734C">--dataset, -s</font><font color="#8B8A88">: str</font><font color="#2D2D2D">────</font><font color="#A2734C"><i>Dataset name or number</i></font>
</pre>


- [Installation Guide](installation.md): Set up `evid` on your system.
- [Usage Guide](usage.md): Learn how to add, browse, and manage documents.
- [Development](development.md): Contribute to `evid` or extend its functionality.

## Quick Start

```bash
uv pip install https://github.com/evidlabel/evid.git
evid
```


