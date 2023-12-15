import json
import typing
from dataclasses import dataclass

@dataclass
class NBBBGradingRequest:
    """The identifier of the assignment upload"""
    id: int
    """The assignment that is requested to grade"""
    assignment: str
    """Raw json of the notebook to grade"""
    notebook: str

    def dump(self) -> str:
        return json.dumps({
            "id": self.id,
            "assignment": self.assignment,
            "notebook": self.notebook
        })

    @classmethod
    def load(cls, data: str):
        o = json.loads(data)
        return cls(o["id"], o["assignment"])

@dataclass
class NBBBGradingResponse:
    """The identifier of the graded assignment"""
    id: int
    success:bool
    """The points achieve in the cells"""
    points: typing.Dict[str, int]

    def dump(self) -> str:
        return json.dumps({
            "id": self.id,
            "success": self.success,
            "points": self.points
        })

    @classmethod
    def load(cls, data: str):
        o = json.loads(data)
        return cls(o["id"], o["success"], o["points"])