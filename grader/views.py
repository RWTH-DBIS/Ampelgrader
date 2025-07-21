import datetime
import typing
import django.http as http
import re
import os
import base64
import json
import time 
from collections import defaultdict
from datetime import timedelta

from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
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

import psycopg2

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

conn = psycopg2.connect(host=os.getenv("NBBB_DB_HOST", "localhost"), 
                dbname=os.getenv("NBBB_DB_NAME", "grader"), 
                user=os.getenv("NBBB_DB_USER", "user"), 
                password=os.getenv("NBBB_DB_PASSWD", "password"))
cursor = conn.cursor()
conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)

def ping(request: http.HttpRequest):

    return http.HttpResponse(b"pong")

def login(request: http.HttpRequest):
    translation.activate(settings.LANGUAGE_CODE)

    return render(request, "grader/login.html", {})

@receiver(user_logged_in)
def store_sid(sender, request, user, **kwargs):
    """
    Store the keycloak session id in the database.
    Check for user role to set user permissions.
    """
    keycloak_token = request.session.get('oidc_id_token', None)

    if keycloak_token:
        decoded_token = decode_token(keycloak_token)
        sid = decoded_token.get("sid")

        # check if roles key is present in decoded token
        if "roles" in decoded_token:
            roles = decoded_token["roles"]
            admin_role = settings.ADMIN_ROLE

            # if user has role "ampel-testgroup" make the user to staff and superuser 
            if admin_role in roles:
                if not user.is_staff:
                    user.is_staff = True
                    user.save()
                    logger.info(f"User {user.username} has been granted staff privileges.")
                if not user.is_superuser:
                    user.is_superuser = True
                    user.save()
                    logger.info(f"User {user.username} has been granted superuser privileges.")
            else: 
                user.is_staff = False
                user.is_superuser = False
                user.save()
        elif settings.DEBUG:
            # for debugging purposes, set user automatically to superuser
            user.is_staff = True
            user.is_superuser = True
            user.save()
            logger.info(f"User {user.username} has been granted staff privileges.")

        # Update session key using keycloak sid
        try:
          with connection.cursor() as cursor:
              # Check if the session already exists
              cursor.execute("SELECT * FROM keycloak_session WHERE keycloak_sid = %s", [sid])
              if cursor.fetchone() is None:
                cursor.execute("INSERT INTO keycloak_session (keycloak_sid, django_sid) VALUES (%s, %s)", 
                              [sid, request.session.session_key])
              else:
                cursor.execute("UPDATE keycloak_session SET django_sid = %s WHERE keycloak_sid = %s", 
                              [request.session.session_key, sid])
        except Exception as e:
            logger.error("Error occured: " + str(e))

        # initialize daily contingent for the user
        user_email = user.email 
        try:
          with connection.cursor() as cursor:
              cursor.execute("SELECT * FROM daily_contingent WHERE user_email = %s", [user_email])
              counter = cursor.fetchone()
              if counter is None:
                date = datetime.now()
                cursor.execute("INSERT INTO daily_contingent (user_email, date, count) VALUES (%s, %s, 0)", [user_email, date])
              else:
                if counter[1] != datetime.now().date():
                  # reset the counter for the new day
                  cursor.execute("UPDATE daily_contingent SET count = 0, date = %s WHERE user_email = %s", [datetime.now(), user_email])                      
        except Exception as e:  
            logger.error("Error occured while initializing daily contingent: " + str(e))

    else:
        logger.error('No keycloak token found in the session')
    
    return 

def check_grading_status(request: http.HttpRequest, for_process: str):
    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    try:
        gq = GradingProcess.objects.get(identifier=for_process)
    except GradingProcess.DoesNotExist:
        return http.HttpResponseNotFound("Not found")
    grading = Grading.objects.filter(process=gq)
    if not grading.exists():
        finished = False
    else:
        finished = True

    response = http.HttpResponse(json.dumps({"finished": finished}), content_type="application/json")
    return response

def show_results(request: http.HttpRequest, for_process: str):
    translation.activate(settings.LANGUAGE_CODE)

    if settings.NEED_GRADING_AUTH and not request.user.is_authenticated:
        return http.HttpResponseRedirect("../login")
    
    try:
        gq = GradingProcess.objects.get(identifier=for_process)
    except GradingProcess.DoesNotExist:
        return http.HttpResponseNotFound("Not found")
    grading = Grading.objects.filter(process=gq)
    if not grading.exists():
        # Check if there was an error
        if ErrorLog.objects.filter(process=gq).exists():
            errorlog = str(ErrorLog.objects.get(process=gq).log)
            logger.info(f"Grading process {gq.identifier} has an error: {errorlog}")
            if 'convert_notebooks' in errorlog:
                return render(request, "grader/grading_error.html", {"error": _("Ein Problem mit der Notebook-Konvertierung ist aufgetreten. Bitte lösche nicht die bestehenden Zellen im Notebook.")})
            return render(request, "grader/grading_error.html", {"error": _("Etwas ist schief gelaufen. Bitte versuche es später noch einmal.")})
        else:
            return render(request, "grader/grading_processing.html", {})
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

            allred = all(elem['t_light_colour'] == 'red' for elem in result)

    return render(request, "grader/result.html", {"result": result, "red": red, "yellow": yellow, "allred": allred})


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
        if not ex.running() and not request.user.is_staff:
            return render(request, "grader/grading_unavailable.html", {"message": _("Zurzeit ist keine Bewertung für diese Übung verfügbar!")})

    except ObjectDoesNotExist:
        return http.HttpResponseNotFound("Exercise not found")
    
    user_email = request.user.email if settings.NEED_GRADING_AUTH else "donotusemeinproduction@example.org"

    # check if user contingent has reached the limit
    with transaction.atomic():
      counter = DailyContingent.objects.raw(
          """
          SELECT * FROM daily_contingent WHERE user_email = %s
          """,
          [user_email],
      )
    
    if not request.user.is_staff:
      if not counter:
          return render(request, "grader/grading_unavailable.html", {"message": _("Etwas ist schief gelaufen. Bitte versuche es später noch einmal.")})
      
      # if date is one day before today, reset the counter
      if counter[0].date != datetime.now().date():
          # with connection.cursor() as cursor:
          #     cursor.execute(
          #         """
          #         UPDATE daily_contingent SET count = 0, date = %s WHERE user_email = %s
          #         """,
          #         [datetime.now(), user_email],
          #     )
          counter[0].count = 0
          counter[0].date = datetime.now().date()

      if counter[0].count >= int(settings.DAILY_LIMIT):
          return render(
              request,
              "grader/grading_unavailable.html",
              {"message": _("Du hast dein tägliches Limit an {} Anfragen erreicht.").format(settings.DAILY_LIMIT)},
          )

    if request.method == "GET":
        files = list()
        release = {}
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

            notebook = Notebook.objects.filter(in_exercise=ex).first()

        id = gp[0].identifier if len(list(gp)) > 0 else None
        
        if notebook and notebook.data:
          files.append({
              "name": notebook.filename if notebook.data else None,
              "assets": f"{notebook.filename}_assets" if notebook.assets else None,
              "updated_at": notebook.uploaded_at.strftime("%d.%m.%Y %H:%M") if notebook else None,
          })
        
        if notebook and notebook.release_data:
          release["filename"] = notebook.filename if notebook.release_data else None

        return render(
            request,
            "grader/request.html",
            {"form": NoteBookForm(), "for_exercise": for_exercise, "id": id, "files": files, "release": release},
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

        enqueue_grading_request(new_gp.identifier)

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
    if not ex.running() and not request.user.is_staff:
        return render(request, "grader/grading_unavailable.html", {"message": _("Zurzeit ist keine Bewertung für diese Übung verfügbar!")})
    
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

def download_release(request: http.HttpRequest, for_notebook: str):
    """
    Downloads the release of the exercise.
    """
    translation.activate(settings.LANGUAGE_CODE)

    notebook = get_object_or_404(Notebook, filename=for_notebook)

    response = http.HttpResponse(notebook.release_data, content_type="application/x-ipynb+json")
    response["Content-Disposition"] = f'attachment; filename="{notebook.filename}"'
    print(response)
    return response

def download_notebook(request: http.HttpRequest, for_notebook: str):
    """
    Downloads the notebook associated with the given exercise.
    """
    translation.activate(settings.LANGUAGE_CODE)

    notebook = get_object_or_404(Notebook, filename=for_notebook)
    
    response = http.HttpResponse(notebook.data, content_type="application/x-ipynb+json")
    response["Content-Disposition"] = f'attachment; filename="{notebook.filename}"'
        
    return response

def download_assets(request: http.HttpRequest, for_notebook: str):
    """
    Downloads the assets associated with the given notebook.
    """
    translation.activate(settings.LANGUAGE_CODE)

    notebook = get_object_or_404(Notebook, filename=for_notebook)

    if not notebook.assets:
        return render(request, "grader/grading_error.html", {"error": _("Ein Problem ist aufgetreten. Es sind keine Assets für dieses Notebook vorhanden. Bitte lade Dir die Assets in Moodle runter.")})

    response = http.HttpResponse(notebook.assets, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{notebook.filename}_assets.zip"'

    return response

def download_notebook(request: http.HttpRequest, for_notebook: str):
    """
    Downloads the notebook associated with the given exercise.
    """
    translation.activate(settings.LANGUAGE_CODE)

    notebook = get_object_or_404(Notebook, filename=for_notebook)

    response = http.HttpResponse(notebook.data, content_type="application/x-ipynb+json")
    response["Content-Disposition"] = f'attachment; filename="{notebook.filename}"'

    return response

def download_assets(request: http.HttpRequest, for_notebook: str):
    """
    Downloads the assets associated with the given notebook.
    """
    translation.activate(settings.LANGUAGE_CODE)

    notebook = get_object_or_404(Notebook, filename=for_notebook)

    if not notebook.assets:
        return http.HttpResponseNotFound("No assets available for this notebook.")

    response = http.HttpResponse(notebook.assets, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{notebook.filename}_assets.zip"'

    return response

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
        assets_files = request.FILES["assets"].read() if "assets" in request.FILES else None
        exercise_identifier = form.cleaned_data["exercise_identifier"]
        subexercise_dict = parse_notebook(loads(notebook_data))
        with transaction.atomic():
            # check if exercise with the same identifier already exists
            if Exercise.objects.filter(identifier=exercise_identifier).exists():
                # update the existing exercise
                ex = Exercise.objects.get(identifier=exercise_identifier)
                ex.start_date = form.cleaned_data["start_date"]
                ex.stop_date = form.cleaned_data["stop_date"]
                ex.last_updated = datetime.now()
                ex.save()

                Notebook.objects.filter(in_exercise=ex).delete()

                nb = Notebook(filename=notebook_file_name, in_exercise=ex, data=notebook_data, assets=assets_files, release_data=None)
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

            else: 
              # create the database entries
              ex = Exercise(
                  exercise_identifier,
                  start_date=form.cleaned_data["start_date"],
                  stop_date=form.cleaned_data["stop_date"],
                  last_updated=datetime.now(),
              )
              ex.save()
              nb = Notebook(filename=notebook_file_name, in_exercise=ex, data=notebook_data, assets=assets_files, uploaded_at=datetime.now(), release_data=None)
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
        enqueue_notebook_update(notebook_file_name)

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
    
def enqueue_grading_request(process_id) -> None:
    logger.info(f"Enqueuing grading request for process ID: {process_id}")
    val = process_id
    cursor.execute(f"NOTIFY grade_notebook, '{val}';")
    time.sleep(1) 

def enqueue_notebook_update(filename) -> None:
    logger.info(f"Enqueuing notebook update for filename: {filename}")
    val = str(filename)
    cursor.execute(f"NOTIFY update_notebook, '{val}';")
    time.sleep(1)

# Logout redirect 
@csrf_exempt
def keycloak_logout(request: http.HttpRequest):
    try: 
        logout_token = decode_token(str(request.body))
        
        if not logout_token:
            return JsonResponse({"status": "error", "message": "No logout token provided"})
        
        sid = logout_token.get("sid")

        try:
          with connection.cursor() as cursor:
              cursor.execute("SELECT django_sid FROM keycloak_session WHERE keycloak_sid = %s", [str(sid)])
              django_sid = cursor.fetchone()[0]
        except Exception as e:
            logger.error("Error occured: " + str(e))
        
        if not django_sid:
            return JsonResponse({"status": "error", "message": "No session ID found."})
        else:
            # Delete the session from the database
            session = Session.objects.get(session_key=django_sid)
            Session.objects.filter(session_key=session.session_key).delete()
        
        try: 
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM keycloak_session WHERE keycloak_sid = %s", [sid])
        except Exception as e:
            logger.error("Error occured: " + str(e))

        # Logout the user
        logout(request)

        logger.info("Backchannel Logout successful")
        return http.HttpResponse(status=200)
    except Exception as e:
        logger.error("Error occured: " + str(e))
        return JsonResponse({"status": "error", "message": str(e)})
    
def decode_token(token:str) -> dict:
    try:
        parts = token.split(".")
        payload = parts[1]
        payload += '=' * (-len(payload) % 4)
        decoded = base64.b64decode(payload).decode('utf-8')
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Error decoding token: {e}")
        return {}