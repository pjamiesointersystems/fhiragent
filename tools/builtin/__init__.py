#from tools.builtin.edit_file import EditTool
#from tools.builtin.glob import GlobTool
#from tools.builtin.grep import GrepTool
#from tools.builtin.list_dir import ListDirTool
#from tools.builtin.memory import MemoryTool
from tools.builtin.edit_file import EditTool
from tools.builtin.fhir_everything import FHIREverythingTool
from tools.builtin.fhir_read import FHIRReadTool
from tools.builtin.fhir_search import FHIRSearchTool
from tools.builtin.fhir_update import FHIRUpdateTool
from tools.builtin.glob import GlobTool
from tools.builtin.grep import GrepTool
from tools.builtin.list_dir import ListDirTool
from tools.builtin.memory import MemoryTool
from tools.builtin.read_file import ReadFileTool
#from tools.builtin.shell import ShellTool
#from tools.builtin.todo import TodosTool
#from tools.builtin.web_fetch import WebFetchTool
#from tools.builtin.web_search import WebSearchTool
from tools.builtin.shell import ShellTool
from tools.builtin.todo import TodosTool
from tools.builtin.web_fetch import WebFetchTool
from tools.builtin.web_search import WebSearchTool
from tools.builtin.write_file import WriteFileTool

__all__ = [
   "ReadFileTool",
   "WriteFileTool",
   "EditTool",
   "ShellTool",
   "ListDirTool",
   "GrepTool",
   "GlobTool",
   "WebSearchTool",
   "WebFetchTool",
   "TodosTool",
   "FHIRSearchTool",
   "FHIRReadTool",
   "FHIRUpdateTool",
   "MemoryTool",
   "FHIREverythingTool",
]


def get_all_builtin_tools() -> list[type]:
    return [
        ReadFileTool,
        WriteFileTool,
        EditTool,
        ShellTool,
        ListDirTool,
        GrepTool,
        GlobTool,
        WebSearchTool,
        WebFetchTool,
        TodosTool,
        FHIRSearchTool,
        FHIRReadTool,
        FHIRUpdateTool,
        MemoryTool, 
        FHIREverythingTool
    ]