import uuid

from django.db import models
from django.contrib import admin
from django.core.validators import MinValueValidator
from datetime import datetime

"""
Models an assignment
"""


class Exercise(models.Model):
    identifier = models.CharField(
        max_length=255, primary_key=True, db_column="identifier"
    )
    start_date = models.DateTimeField(
        "Starting date exercise grading", db_column="start_date"
    )
    stop_date = models.DateTimeField("End date exercise grading", db_column="stop_date")

    def __str__(self):
        return f"ID: {self.identifier}. Correction from {self.start_date} to {self.stop_date}."

    @admin.display(
        boolean=True,
        description="Running",
    )
    def running(self):
        """
        Returns whether the exercise is currently running.
        Note: uses system configured time!
        """
        n = datetime.now().timestamp()
        return self.start_date.timestamp() <= n <= self.stop_date.timestamp()

    class Meta:
        db_table = "exercise"


class GradingProcess(models.Model):
    identifier = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, db_column="identifier"
    )
    email = models.EmailField(db_column="email")
    requested_at = models.DateTimeField(auto_now_add=True, db_column="requested_at")
    for_exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, db_column="for_exercise"
    )
    notified = models.BooleanField("User Notified", db_column="notified", default=False)

    def __str__(self):
        return f"ID: {self.identifier} for email: {self.email}. Request at: {self.requested_at.__str__()}"

    @admin.display(boolean=True, description="Processed")
    def processed(self):
        return Grading.objects.filter(process=self.identifier).exists()

    class Meta:
        db_table = "gradingprocess"


"""
Describes a Notebook in an Exercise, having multiple subexercises
Currently, we associate notebook and Exercise with a 1-1 mapping.
However, we leave notebook as its own entity to maybe support multiple notebooks in the future
"""


class Notebook(models.Model):
    filename = models.CharField(max_length=255, primary_key=True, db_column="filename")
    in_exercise = models.OneToOneField(
        Exercise, on_delete=models.CASCADE, db_column="in_exercise"
    )

    class Meta:
        db_table = "notebook"

    def __str__(self):
        return f"{self.filename} (exercise {self.in_exercise})"


"""
Describes a subexercise in the Notebook (such as 2). This defines the coarsness of the grading presented to the studies
For each of these SubExercises, the student will see how good they were
"""


class SubExercise(models.Model):
    label = models.CharField(max_length=255, db_column="label")
    in_notebook = models.ForeignKey(
        Notebook, on_delete=models.CASCADE, db_column="in_notebook"
    )

    class Meta:
        db_table = "subexercise"

    def __str__(self):
        return f"'{self.label}'({self.in_notebook.in_exercise})"


"""
Describes a single cell in a notebook and its maxscore and to which subexercise it belongs
"""


class Cell(models.Model):
    cell_id = models.CharField(max_length=255, db_column="cell_id")
    sub_exercise = models.ForeignKey(
        SubExercise, on_delete=models.CASCADE, db_column="sub_exercise"
    )
    max_score = models.IntegerField(
        validators=[MinValueValidator(0)], db_column="max_score"
    )

    class Meta:
        db_table = "cell"

    def __str__(self):
        return f"Cell id: {self.cell_id} in subexercise {self.sub_exercise.label}"


# Django does not allow multiple primary keys, therefore we just let Django generate an ide field and use an unique contraint
class Grading(models.Model):
    process = models.ForeignKey(
        GradingProcess, on_delete=models.CASCADE, db_column="process"
    )
    # Important: This is the primary key of the cell table NOT THE CELL ID AS IN THE NOTEBOOK!
    # This is because we are not sure if we can assume that the cell id is globally unique
    cell = models.ForeignKey(Cell, on_delete=models.CASCADE, db_column="cell")
    points = models.IntegerField(db_column="points")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["process", "cell"], name="unique_grading_for_cell_in_process"
            )
        ]
        db_table = "grading"

    def __str__(self):
        return f"process: {self.process.identifier} cell: {self.cell.cell_id}: {self.points}"


"""
Models an error happened throughout the grading process.
Is used to indicate that a grading process was finished but resulted in an error.
"""


class ErrorLog(models.Model):
    process = models.OneToOneField(
        GradingProcess, on_delete=models.CASCADE, db_column="process"
    )
    log = models.TextField(db_column="log")

    class Meta:
        db_table = "errorlog"


"""
Models the assignment to workers
"""


class WorkerAssignment(models.Model):
    worker_id = models.UUIDField(
        default=uuid.uuid4, editable=False, db_column="worker_id"
    )
    assigned_at = models.DateTimeField(
        auto_now_add=True, editable=False, db_column="assigned_at"
    )
    process = models.ForeignKey(
        GradingProcess, on_delete=models.CASCADE, db_column="process"
    )

    class Meta:
        db_table = "workerassignment"


"""
Models a notebook uploaded by a student
"""


class StudentNotebook(models.Model):
    data = models.BinaryField(db_column="data")
    notebook = models.ForeignKey(
        Notebook, on_delete=models.CASCADE, db_column="notebook"
    )
    process = models.ForeignKey(
        GradingProcess, on_delete=models.CASCADE, primary_key=True, db_column="process"
    )

    class Meta:
        db_table = "studentnotebook"
