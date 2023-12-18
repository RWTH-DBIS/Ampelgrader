import json
import typing
from dataclasses import dataclass

@dataclass
class NBBBGradingRequest:
    """The identifier of the assignment upload"""
    id: int
    """The assignment that is requested to grade"""
    assignment: str
    """Raw json for the student notebooks to grade.
        Key: Notebook file name
        Value: Raw content of the notebook
        The filename needs to be the same as it was in the assignment, otherwise NBGrade wont be able to 
        find the notebook for grading. Therefore we include the filename here.
        Note that the NBWorker is not able to process more than one notebook at this time,
        but fixing this would be relatively straightforward, albeit not needed at the moment.
    """
    notebook: typing.Dict[str, str]

    def dump(self) -> str:
        return json.dumps({
            "id": self.id,
            "assignment": self.assignment,
            "notebook": self.notebook
        })

    @classmethod
    def load(cls, data: str):
        o = json.loads(data)
        return cls(o["id"], o["assignment"], o["notebook"])

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