from django.contrib import admin

from .models import *

# Register your models here.


class CellInline(admin.TabularInline):
    model = Cell
    extra = 3


class GradingInline(admin.TabularInline):
    model = Grading


class ErrorLogInline(admin.StackedInline):
    model = ErrorLog


class StudentNotebookInline(admin.StackedInline):
    model = StudentNotebook


class SubExercisesAdmin(admin.ModelAdmin):
    model = SubExercise
    extra = 1
    inlines = [CellInline]
    list_filter = ["in_notebook"]
    list_display = ["in_notebook", "label"]


class NotebookAdmin(admin.StackedInline):
    model = Notebook


class ExerciseAdmin(admin.ModelAdmin):
    model = Exercise
    inlines = [NotebookAdmin]
    list_display = ["identifier", "start_date", "stop_date", "running"]


class ProcessAdmin(admin.ModelAdmin):
    model = GradingProcess
    inlines = [GradingInline, StudentNotebookInline, ErrorLogInline]
    list_display = ["identifier", "email", "requested_at", "for_exercise", "processed"]


admin.site.register(Exercise, ExerciseAdmin)

admin.site.register(SubExercise, SubExercisesAdmin)

admin.site.register(GradingProcess, ProcessAdmin)

admin.site.register(StudentNotebook)

admin.site.register(WorkerAssignment)

admin.site.register(Grading)

admin.site.register(ErrorLog)
