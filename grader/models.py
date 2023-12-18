import uuid

from django.db import models


class Exercise(models.Model):
    identifier = models.CharField(max_length=255, primary_key=True)
    startDate = models.DateField()
    stopDate = models.DateField()

    def __str__(self):
        return f"ID: {self.identifier} Correction from {self.startDate} to {self.stopDate}."

class GradingProcess(models.Model):
    identifier = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    requestedAt = models.DateTimeField(auto_now_add=True)
    forExercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)

    def __str__(self):
        return f"ID: {self.identifier} for email: {self.email}. Request at: {self.requestedAt.__str__()}"


class Notebook(models.Model):
    filename = models.CharField(max_length=255, primary_key=True)
    inExercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)



class Grading(models.Model):
    processId = models.OneToOneField(GradingProcess, on_delete=models.CASCADE)
    points = models.IntegerField()

"""
Describes a subexercise in the Notebook (such as 2). This defines the coarsness of the grading presented to the studies
For each of these SubExercises, the studen will see how good they were
"""
class SubExercise(models.Model):
    inNotebook = models.ForeignKey(Notebook, on_delete=models.CASCADE)

"""
Describes a single cell in a notebook and its maxscore and to which subexercise it belongs
"""
class Cell(models.Model):
    cellId = models.CharField(max_length=255, primary_key=True)
    maxScore = models.IntegerField()
    subExercise = models.ForeignKey(SubExercise, on_delete=models.CASCADE)