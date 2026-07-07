"""
NotebookEditTool – edit Jupyter notebook cells.

Port of: src/tools/NotebookEditTool/NotebookEditTool.ts
"""
from __future__ import annotations
import json, os
from typing import Any

TOOL_NAME = "NotebookEdit"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "notebook_path": {"type": "string"},
            "cell_index": {"type": "number"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "is_new_cell": {"type": "boolean"},
            "cell_type": {"type": "string", "enum": ["code", "markdown"]},
        },
        "required": ["notebook_path", "cell_index", "new_string"],
    }

async def call(
    notebook_path: str,
    cell_index: int,
    new_string: str,
    old_string: str = "",
    is_new_cell: bool = False,
    cell_type: str = "code",
    **kwargs: Any,
) -> dict[str, Any]:
    if not os.path.isabs(notebook_path):
        notebook_path = os.path.join(os.getcwd(), notebook_path)
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        cells = nb.get("cells", [])
        if is_new_cell:
            new_cell = {
                "cell_type": cell_type,
                "metadata": {},
                "source": new_string.split("\n") if new_string else [],
                "outputs": [] if cell_type == "code" else None,
            }
            if cell_type == "code":
                new_cell["execution_count"] = None
            cells.insert(cell_index, new_cell)
        else:
            if cell_index < 0 or cell_index >= len(cells):
                return {"error": f"Cell index {cell_index} out of range (0-{len(cells)-1})"}
            cell = cells[cell_index]
            source = "".join(cell.get("source", []))
            if old_string and old_string not in source:
                return {"error": "old_string not found in cell"}
            if old_string:
                source = source.replace(old_string, new_string, 1)
            else:
                source = new_string
            cell["source"] = source.split("\n") if source else []
        nb["cells"] = cells
        with open(notebook_path, "w", encoding="utf-8") as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)
        return {"data": f"{'Inserted' if is_new_cell else 'Updated'} cell {cell_index}"}
    except Exception as e:
        return {"error": str(e)}
