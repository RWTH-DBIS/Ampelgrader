import uuid

from django.db import models
from django.contrib import admin
from django.core.validators import MinValueValidator
from datetime import datetime

"""
Models an assignment
"""
class Exercise(models.Model):
    identifier = models.CharField(max_length=255, primary_key=True)
    start_date = models.DateTimeField("Starting date exercise grading")
    stop_date = models.DateTimeField("End date exercise grading")

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


class GradingProcess(models.Model):
    identifier = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    requested_at = models.DateTimeField(auto_now_add=True)
    for_exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.identifier} for email: {self.email}. Request at: {self.requestedAt.__str__()}"

    class Meta:
        db_table="gradingprocess"
"""
Describes a Notebook in an Exercise, having multiple subexercises
Currently, we associate notebook and Exercise with a 1-1 mapping.
However, we leave notebook as its own entity to maybe support multiple notebooks in the future
"""
class Notebook(models.Model):
    filename = models.CharField(max_length=255, primary_key=True)
    in_exercise = models.OneToOneField(Exercise, on_delete=models.CASCADE)


"""
Describes a subexercise in the Notebook (such as 2). This defines the coarsness of the grading presented to the studies
For each of these SubExercises, the studen will see how good they were
"""
class SubExercise(models.Model):
    label = models.CharField(max_length=255)
    in_notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE)


"""
Describes a single cell in a notebook and its maxscore and to which subexercise it belongs
"""
class Cell(models.Model):
    cell_id = models.CharField(max_length=255)
    sub_exercise = models.ForeignKey(SubExercise, on_delete=models.CASCADE)
    max_score = models.IntegerField(validators=[MinValueValidator(0)])


# Django does not allow multiple primary keys, therefore we just let Django generate an ide field and use an unique contraint
class Grading(models.Model):
    process = models.OneToOneField(GradingProcess, on_delete=models.CASCADE)
    cell_id = models.OneToOneField(Cell, on_delete=models.CASCADE)
    points = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['process_id', 'cell_id'], name='unique_grading_for_cell_in_process'
            )
        ]
        db_table="grading"

"""
Models an error happened throughout the grading process.
Is used to indicate that a grading process was finished but resulted in an error.
"""
class ErrorLog(models.Model):
    process = models.OneToOneField(GradingProcess, on_delete=models.CASCADE)
    log = models.TextField()
    class Meta:
        db_table="errorlog"

"""
Models the assignment to workers
"""
class WorkerAssignment(models.Model):
    worker_id = models.UUIDField(default=uuid.uuid4, editable=False)
    assigned_at = models.DateTimeField(auto_now_add=True, editable=False)
    process = models.ForeignKey(GradingProcess, on_delete=models.CASCADE)

    class Meta:
        db_table="workerassignment"

"""
Models a notebook uploaded by a student
"""
class StudentNotebook(models.Model):
    data = models.BinaryField()
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE)
    process = models.ForeignKey(GradingProcess, on_delete=models.CASCADE, primary_key=True)

    class Meta:
        db_table="studentnotebook"