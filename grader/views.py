import datetime
import typing
import django.http as http
import re
import os
import base64
import json

from collections import defaultdict
from datetime import timedelta

from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import transaction, connection
from django.conf import settings
from django.utils.translation import gettext as _
from django.utils import translation
from django.utils import timezone
from django.contrib.sessions.models import Session

from django.http import JsonResponse
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt

from grader.models import *

import asyncio
import asyncpg

from pgqueuer.qm import QueueManager
from pgqueuer.db import AsyncpgDriver

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def ping(request: http.HttpRequest):

    return http.HttpResponse(b"pong")


def login(request: http.HttpRequest):
    translation.activate(settings.LANGUAGE_CODE)

    return render(request, "grader/login.html", {})

@receiver(user_logged_in)
def store_sid(sender, request, user, **kwargs):
    logger.info('User session ID: ' + request.session.session_key)
    keycloak_token = request.session.get('oidc_id_token', None)

    if keycloak_token:
        decoded_token = decode_token(keycloak_token)
        sid = decoded_token.get("sid")

        # Update session key using keycloak sid
        try:
            session = Session.objects.get(session_key=request.session.session_key)
            session.session_key = sid
            session.save()
            logger.info('Session ID stored in the database: ' + sid)
        except Session.DoesNotExist:
            logger.error('Session does not exist')
    else:
        logger.error('No keycloak token found in the session')
        
    return 

def show_results(request: http.HttpRequest, for_process: str):
    translation.activate(settings.LANGUAGE_CODE)

    try:
        gq = GradingProcess.objects.get(identifier=for_process)
    except GradingProcess.DoesNotExist:
        return http.HttpResponseNotFound("Not found")
    grading = Grading.objects.filter(process=gq)
    if not grading.exists():
        # Check if there was an error
        if ErrorLog.objects.filter(process=gq).exists():
            return render(request, "grader/grading_error.html", {})
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

            red_percentage = float(settings.PERCENTAGE_LIMITS['RED'])
            yellow_percentage = float(settings.PERCENTAGE_LIMITS['YELLOW'])

            """traffic light colour"""
            lower_limit = red_percentage
            upper_limit = yellow_percentage
            if percentage_res < red_percentage:
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

            red = red_percentage*100
            yellow = yellow_percentage*100

    return render(request, "grader/result.html", {"result": result, "red": red, "yellow": yellow})


"""
Grading Request handling
"""
from .forms import NoteBookForm

def show_exercises(request):
    translation.activate(settings.LANGUAGE_CODE)

    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    context_exercises = list()

    for ex in Exercise.objects.all():
        context_exercises.append({
            "identifier": ex.identifier,
            "active": ex.running()
        })

    user_email = request.user.email if settings.NEED_GRADING_AUTH else "donotusemeinproduction@example.org"

    # check if user has already a submission running
    with transaction.atomic():
        gp = GradingProcess.objects.raw(
            """
        SELECT identifier, email FROM gradingprocess WHERE 
        identifier NOT IN (SELECT process FROM errorlog)
        AND email = %s ORDER BY requested_at DESC LIMIT 1
        """,
            [user_email], 
        )

        id = gp[0].identifier if len(list(gp)) > 0 else None

    return render(request, "grader/exercise_overview.html", {"exercises": context_exercises, "id": id})


def request_grading(request: http.HttpRequest, for_exercise: str):
    translation.activate(settings.LANGUAGE_CODE)
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
    
    user_email = request.user.email if settings.NEED_GRADING_AUTH else "donotusemeinproduction@example.org"

    if request.method == "GET":
        # check if user has already a submission running
        with transaction.atomic():
            gp = GradingProcess.objects.raw(
                """
            SELECT identifier, email FROM gradingprocess WHERE 
            identifier NOT IN (SELECT process FROM errorlog)
            AND email = %s ORDER BY requested_at DESC LIMIT 1
            """,
                [user_email],
            )

        id = gp[0].identifier if len(list(gp)) > 0 else None

        return render(
            request,
            "grader/request.html",
            {"form": NoteBookForm(), "for_exercise": for_exercise, "id": id},
        )
    if request.method != "POST":
        return http.HttpResponseNotAllowed("Method not allowed")

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
                _("A grading was already requested by this student.")
            )
        
    with transaction.atomic():
        gp_time = GradingProcess.objects.raw(
            """
        SELECT identifier, requested_at FROM gradingprocess WHERE 
        identifier NOT IN (SELECT process FROM errorlog) 
        AND email = %s AND for_exercise = %s ORDER BY requested_at DESC LIMIT 1
        """,
            [user_email, for_exercise],
        )

        # check if the last request was less than 5 minutes ago
        if len(list(gp_time)) > 0:
            target_time = gp_time[0].requested_at + timedelta(seconds=settings.REQUEST_TIME_LIMIT)
            remaining_time = target_time - timezone.now()
            if remaining_time.total_seconds() > 1:
                return HttpResponseRedirect(
                    "/grader/request/{}/counter".format(for_exercise)
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

        asyncio.run(enqueue_grading_request(new_gp.identifier))

            # we are done
        return HttpResponseRedirect("/grader/successful_request?id={}".format(new_gp.identifier))
    else:
        return http.HttpResponseBadRequest("Invalid form")

def counter(request: http.HttpRequest, for_exercise: str):
    translation.activate(settings.LANGUAGE_CODE)

    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    try:
        ex = Exercise.objects.get(identifier=for_exercise)
    except ObjectDoesNotExist:
        return http.HttpResponseNotFound("Exercise not found")
    if not ex.running():
        return render(request, "grader/grading_unavailable.html")
    
    user_email = request.user.email if settings.NEED_GRADING_AUTH else "donotusemeinproduction@example.org"

    with transaction.atomic():
        gp_time = GradingProcess.objects.raw(
            """
        SELECT identifier, requested_at FROM gradingprocess WHERE 
        identifier NOT IN (SELECT process FROM errorlog) 
        AND email = %s AND for_exercise = %s ORDER BY requested_at DESC LIMIT 1
        """,
            [user_email, for_exercise],
        )

    target_time = gp_time[0].requested_at + timedelta(seconds=settings.REQUEST_TIME_LIMIT)
    time_limit_minutes = settings.REQUEST_TIME_LIMIT // 60
    remaining_time = target_time - timezone.now()
    
    if remaining_time.total_seconds() <= 0:
        return HttpResponseRedirect("/grader/request/{}".format(for_exercise))
    
    hours = remaining_time.seconds // 3600
    minutes = (remaining_time.seconds // 60) % 60
    seconds = remaining_time.seconds % 60

    data = {
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
    }

    return render(request, "grader/counter.html", {"data": data, "for_exercise": for_exercise, "minutes": time_limit_minutes})

def successful_request(request: http.HttpRequest):
    translation.activate(settings.LANGUAGE_CODE)

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
            _("Given dict does not contain the necessary top-level 'cells' field")
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
            raise ValueError(_("Given dict has invalid format. Key error: ") + str(e))
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
                last_updated=datetime.now(),
            )
            ex.save()
            nb = Notebook(filename=notebook_file_name, in_exercise=ex, data=notebook_data, uploaded_at=datetime.now())
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

        # trigger nbgrader to update notebook and generate assignments
        asyncio.run(enqueue_notebook_update(notebook_file_name))

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

async def enqueue_grading_request(process_id) -> None:
    # Establish a database connection; asyncpg and psycopg are supported.
    connection = await asyncpg.connect(            
            host=os.getenv("NBBB_DB_HOST"),  # Replace with your host
            database=os.getenv("NBBB_DB_NAME"),  # Replace with your database name
            user=os.getenv("NBBB_DB_USER"),  # Replace with your username
            password=os.getenv("NBBB_DB_PASSWD")  # Replace with your password)
    )

    # Initialize a database driver
    driver = AsyncpgDriver(connection)
    # Create a QueueManager instance
    qm = QueueManager(driver)

    await qm.queries.enqueue(
        ["grade_notebook"],
        [str(process_id).encode()],
    )

async def enqueue_notebook_update(filename) -> None:
    # Establish a database connection; asyncpg and psycopg are supported.
    connection = await asyncpg.connect(            
            host=os.getenv("NBBB_DB_HOST"),  # Replace with your host
            database=os.getenv("NBBB_DB_NAME"),  # Replace with your database name
            user=os.getenv("NBBB_DB_USER"),  # Replace with your username
            password=os.getenv("NBBB_DB_PASSWD")  # Replace with your password)
    )

    # Initialize a database driver
    driver = AsyncpgDriver(connection)
    # Create a QueueManager instance
    qm = QueueManager(driver)

    await qm.queries.enqueue(
        ["update_notebook"],
        [str(filename).encode()],
    )


# Logout redirect 
@csrf_exempt
def keycloak_logout(request: http.HttpRequest):
    try:
        logger.info("Request Body received: " + str(request.body))

        logout_token = decode_token(str(request.body))
        
        if not logout_token:
            return JsonResponse({"status": "error", "message": "No logout token provided"})
        
        sid = logout_token.get("sid")
        
        if not sid:
            return JsonResponse({"status": "error", "message": "No session ID found in the logout token"})
        else:
            logger.info('Session ID found in the logout token:' + sid)
            # Delete the session from the database
            Session.objects.filter(session_key=sid).delete()
            logger.info('Session deleted from the database')

        # Logout the user
        logout(request)

        logger.info("Logout successful")
        return http.HttpResponse(status=200)
    except Exception as e:
        logger.error("Error occured: " + str(e))
        return JsonResponse({"status": "error", "message": str(e)})
    
def decode_token(token:str) -> dict:
    parts = token.split(".")
    payload = parts[1]
    payload += '=' * (-len(payload) % 4)
    decoded = base64.b64decode(payload).decode('utf-8')
    logger.info(f"Decoded token: {decoded}")
    return json.loads(decoded)