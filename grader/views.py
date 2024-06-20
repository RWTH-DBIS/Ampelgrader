import datetime
import typing
import django.http as http
import re

from collections import defaultdict

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction, connection
from django.conf import settings

from grader.models import *


def ping(request: http.HttpRequest):
    return http.HttpResponse(b"pong")


def login(request: http.HttpRequest):
    return render(request, "grader/login.html", {})


def show_results(request: http.HttpRequest, for_process: str):
    try:
        gq = GradingProcess.objects.get(identifier=for_process)
    except GradingProcess.DoesNotExist:
        return http.HttpResponseNotFound("Not found")
    grading = Grading.objects.filter(process=gq)
    if not grading.exists():
        # Check if there was an error
        if ErrorLog.objects.filter(process=gq).exists():
            return http.HttpResponseBadRequest("Something went wrong. Please check your notebook and try again. If the error persists, please contact us.")
        else:
            return render(request, "grader/grading_processing.html", {})
            #return http.HttpResponseNotFound("Grading process not finished. Thank you for your patience")
    result = list()
    with connection.cursor() as cursor:
        cursor.execute("""
        SELECT subexercise.label, SUM(grading.points) as achieved, SUM(cell.max_score) as max_points FROM grading 
            JOIN cell ON grading.cell = cell.id
            JOIN subexercise ON cell.sub_exercise = subexercise.id
            WHERE
                grading.process = %s 
            GROUP BY subexercise.label
        """, [str(gq.identifier)])

        """calulate result percentage"""
        for row in cursor.fetchall():
            score = row[1]
            max_score = row[2]
            
            """calculate result percentage"""
            percentage_res = (score/max_score)

            """traffic light colour"""
            lower_limit = settings.PERCENTAGE_LIMITS['RED']
            upper_limit = settings.PERCENTAGE_LIMITS['YELLOW']
            if percentage_res < settings.PERCENTAGE_LIMITS['RED']:
                t_light_colour = "red"
            elif lower_limit <= percentage_res < upper_limit:
                t_light_colour = "yellow"
            else:
                t_light_colour = "green"

            result.append({
                "label": row[0],
                "score": score,
                "max_score": max_score,
                "percentage_res": percentage_res,
                "t_light_colour": t_light_colour
            })

    return render(request, "grader/result.html", {"result": result})



"""
Grading Request handling
"""
from .forms import NoteBookForm

def show_exercises(request):
    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    context_exercises = list()

    for ex in Exercise.objects.all():
        context_exercises.append({
            "identifier": ex.identifier,
            "active": ex.running()
        })

    return render(request, "grader/exercise_overview.html", {"exercises": context_exercises})


def request_grading(request: http.HttpRequest, for_exercise: str):
    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    try:
        ex = Exercise.objects.get(identifier=for_exercise)
        # first of all, check whether it is currently allowed to process this
        if not ex.running():
            return render(request, "grader/grading_unavailable.html")
            #return http.HttpResponseForbidden("At this time, no grading for this exercise is provided. Please go away.")
    except ObjectDoesNotExist:
        return http.HttpResponseNotFound("Exercise not found")
    if request.method == "GET":
        return render(
            request,
            "grader/request.html",
            {"form": NoteBookForm(), "for_exercise": for_exercise},
        )
    if request.method != "POST":
        return http.HttpResponseNotAllowed("Method not allowed")

    user_email = request.user.email if settings.NEED_GRADING_AUTH else "donotusemeinproduction@example.org"

    # check if user has already a submission running
    with transaction.atomic():
        gp = GradingProcess.objects.raw(
            """
        SELECT identifier, email FROM gradingprocess WHERE 
        identifier NOT IN (SELECT process FROM grading) AND identifier NOT IN (SELECT process FROM errorlog)
        AND email = %s LIMIT 1
        """,
            [user_email],
        )
        # .exist() does not exist for RawQuerySet(lul)
        if len(list(gp)) > 0:
            return http.HttpResponseForbidden(
                "A grading was already requested by this student."
            )
    form = NoteBookForm(request.POST, request.FILES)
    # check if the form is correct
    if form.is_valid():
        # extract the binary file data of the notebook
        notebook_data = request.FILES["notebook"].read()
        # get the one-to-one related notebook "blueprint" for the Exercise
        valid_nb = ex.notebook
        # we have all the data we need to create the grading process
        with transaction.atomic():
            new_gp = GradingProcess(email=user_email, for_exercise=ex)
            new_gp.save()
            new_sn = StudentNotebook(
                data=notebook_data, process=new_gp, notebook=valid_nb
            )
            new_sn.save()
            # we are done
        return HttpResponseRedirect("/grader/successful_request?id={}".format(new_gp.identifier))
    else:
        return http.HttpResponseBadRequest("Invalid form")


def successful_request(request: http.HttpRequest):
    if request.method != "GET":
        return http.HttpResponseNotAllowed("Not allowed")
    
    id = request.GET.get('id', default='UNKNOWN')
    return render(request, "grader/successful_request.html", {"id": id})
    #return http.HttpResponse(f"Grading was requested. You will hear from us. Your process ID is: {request.GET.get('id', default='UNKNOWN')}")


"""
Administration utilities
"""
from json import loads
from .forms import AutoCreationForm


def parse_notebook(nb: typing.Dict) -> typing.Dict[str, typing.Dict[str, float]]:
    """
    Parses a jupyter notebook to extract the association between subexercises and cell ids.
    Raises value error if the given notebook dict has an unexpected format
    Parameter:
        nb: A parsed jupyter notebook json
    Returns:
        A dictionary containing for each subexercise identifier present a dicitionary containing
        for each cell id (nbgraders grade id) the number of points achievable
    """
    subexercise_identifier_re = re.compile("""\A#subexercise:(.+)""")
    if "cells" not in nb:
        raise ValueError(
            "Given dict does not contain the necessary top-level 'cells' field"
        )
    res = defaultdict(lambda: dict())
    cells_array: typing.List[typing.Dict] = nb["cells"]

    # filter to extract only solution cells:
    def _filter(cell: typing.Dict) -> bool:
        try:
            # if a cell does not correspond to the expected format, we will automatically discard it
            return bool(cell["metadata"]["nbgrader"]["grade"])
        except KeyError:
            return False

    for cell in filter(_filter, cells_array):
        try:
            if cell["cell_type"] == "code":
                for l in cell["source"]:
                    str_l = str(l)
                    m = subexercise_identifier_re.search(str_l)
                    if m is not None:
                        cell_id = cell["metadata"]["nbgrader"]["grade_id"]
                        max_points = float(cell["metadata"]["nbgrader"]["points"])
                        sub_exericse_identifier = m.group(1)
                        res[sub_exericse_identifier][cell_id] = max_points
        except KeyError as e:
            raise ValueError("Given dict has invalid format. Key error: " + str(e))
    return res


def autoprocess_notebook(request: http.HttpRequest):
    """
    use the notebook form to create a new exercise associated with a notebook and some subexercises for the notebook with the cells.
    Automatically extracts the correct subexercises from comments in the exercise solution cells with the following format:
        #subexercise:'RDF building'
    """
    if not request.user.is_authenticated:
        return http.HttpResponseRedirect("login")
    if not request.user.is_staff:
        return http.HttpResponseForbidden("Staff only")
    if request.method == "GET":
        return render(request, "grader/autocreation.html", {"form": AutoCreationForm()})
    if request.method != "POST":
        return http.HttpResponseNotAllowed("Method not allowed")
    form = AutoCreationForm(request.POST, request.FILES)
    if form.is_valid():
        notebook_file_name = request.FILES["notebook"].name
        notebook_data = request.FILES["notebook"].read()
        exercise_identifier = form.cleaned_data["exercise_identifier"]
        subexercise_dict = parse_notebook(loads(notebook_data))
        with transaction.atomic():
            # create the database entries
            ex = Exercise(
                exercise_identifier,
                start_date=form.cleaned_data["start_date"],
                stop_date=form.cleaned_data["stop_date"],
            )
            ex.save()
            nb = Notebook(filename=notebook_file_name, in_exercise=ex)
            nb.save()
            for subexercise_ident in subexercise_dict.keys():
                sbe = SubExercise(label=subexercise_ident, in_notebook=nb)
                sbe.save()
                for cell_id in subexercise_dict[subexercise_ident]:
                    cell = Cell(
                        cell_id=cell_id,
                        sub_exercise=sbe,
                        max_score=subexercise_dict[subexercise_ident][cell_id],
                    )
                    cell.save()

        # transform the result into a structure easier to use in django template engine:
        # you cannot straigthforward use variables content as keys to access a dictionary
        context_list = list()
        for subexercise_identifier in subexercise_dict.keys():
            h = {"identifier": subexercise_identifier, "cells": []}
            for cell in subexercise_dict[subexercise_identifier].keys():
                h["cells"].append(
                    {
                        "identifier": cell,
                        "points": subexercise_dict[subexercise_identifier][cell],
                    }
                )
            context_list.append(h)
        return render(
            request,
            "grader/autocreation_result.html",
            {"exercise_identifier": exercise_identifier, "result": context_list},
        )
    else:
        return http.HttpResponseBadRequest("Invalid form")
