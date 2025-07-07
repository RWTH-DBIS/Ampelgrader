# 🚦 Ample-Grader

The nbgrader-blackbox, also known as 🚦-grader (Ample-Grader), is a service that enables students to asses their performance on assigned exercise notebooks before the final deadline.\
It does not reveal the results of each individual cell in the notebook; instead, it provides feedback on each subexercise using an ample rating system, where each step can be defined by the lecturer.\
This approach strikes a balance between offering useful feedback and maintaining the integrity of the learning process.\
For students, it encourages iterative learning, offers motivational feedback, and helps reduce performance anxiety. Students can submit their work multiple times before the deadline, allowing them to evaluate how well they meet the criteria and receive intuitive feedback through the rating system (🔴 red, 🟡 yellow, 🟢 green), rather than focusing solely on the total points achieved. This reduces pressure and allows them to fail safely, analyze their mistakes, and ultimately succeed by the final submission.\
For lecturers, the integrity of the assignment is preserved through per-subexercise correctness, along with timer and counter restrictions on grading the notebooks. These measures discourage answer mining and gaming of the 🚦-grader. Lecturers can define the sub-exercises and rating thresholds to align with learning objectives while monitoring the ratings of each sub-exercise, facilitating early diagnosis of difficult topics. This service is suitable for all class sizes.\
The service primarily consists of two components: the ⬛ NBBlackbox, which provides the web interface for lecturers and students, and the 👷 NBworker, responsible for grading the notebooks.
These components communicate through a postgres database, the datamodel is documentated [here](datamodel.md).

## ⬛ NBBlackbox
The ⬛ `NBBlackbox` is a Django-based web application that serves as the main interface for both lecturers and students. It manages user authentication (OIDC/Keycloak), exercise creation, notebook submission, and feedback delivery. The core logic is implemented in the `grader` app, which handles all database interactions, notebook parsing, grading requests, and result aggregation.

**Key Features:**
- OIDC-based authentication (e.g. RWTH single sign-on) with role-based access (admin/staff/student) and session management via Keycloak.
- Time window and daily counter restrictions for grading requests, enforced per user.
- Submission of Jupyter notebooks for preliminary grading, with support for multiple attempts and intuitive traffic-light feedback (🔴🟡🟢) per subexercise.
- Automatic parsing and processing of notebooks for exercise creation, using subexercise tags (e.g. `#subexercise:<LABEL>`) in grading cells.
- Admin interface and autocreation form for managing exercises, notebooks, and assets.
- Real-time feedback on grading status, error handling, and notification of results via email.
- Handles high concurrency by offloading grading jobs to the 👷 NBworker via PostgreSQL notifications.

**Workflow:**
1. Lecturers create or update exercises by uploading notebooks (and optional assets) via the `/grader/autocreation` form. Subexercise tags are parsed automatically.
2. Lecturers configure grading time windows and exercise metadata.
3. Students select an exercise at `/grader/request` and submit their notebook for grading. Daily and time-based limits are enforced per user.
4. Grading requests and submissions are stored in the database and picked up by the 👷 NBworker for autograding.
5. Once grading is complete, results are written back to the database and students are notified. Results are shown as aggregated traffic-light ratings per subexercise, not per cell.
6. Errors or processing states are handled gracefully, with user-friendly feedback and retry options.

## 👷 NBworker
The 👷 `NBworker` is a Python-based background service responsible for grading submitted Jupyter notebooks. It operates independently from the main web application and listens for grading jobs via PostgreSQL notifications. When a student submits a notebook, the NBworker retrieves the submission and assignment metadata from the database, ensures the assignment is up to date, and then uses `nbgrader` to autograde the notebook. The results are written back to the database for further processing and student feedback.

**Key Aspects:**
- Listens for grading and update events from the database using PostgreSQL's `LISTEN/NOTIFY` mechanism.
- Retrieves student submissions and assignment data from the database.
- Ensures the assignment notebook and assets are current and available in the grading environment.
- Uses `nbgrader`'s API to autograde the notebook for a dummy student (submissions are always overwritten for this user).
- Stores grading results and logs back in the database, and notifies the main application when grading is complete.
- Handles errors and updates assignment notebooks as needed.

**Workflow:**
1. NBworker starts and connects to the database, registering for relevant notification channels.
2. When a grading job is submitted, NBworker fetches the notebook and assignment, updates the local copy if needed, and autogrades the submission.
3. Grading results are inserted into the database, and a notification is sent to inform the main application and student.
4. Assignment updates are handled automatically if a new version is detected or requested.

For configuration check `./nbworker/Readme.md`

## Getting Started
For developing, you can use the shipped 'docker-compose-dev.yaml' file, which defines all necessary configurations, such as the oidc provider and mounted volumes and the postgres database:

``docker-compose -f docker-compose-dev.yaml up``

### Preparing the jupyter notebooks

There are two ways for configuring the nbblackbox for notebooks.
The easier way is via the autocreation form, which parses the notebooks and looks for subexercise-tags of the form ``#subexercise:<LABEL>`` in the grading cells of nb-grader created notebooks.
The more complex way is to use the django-generated admin tools under /admin.

### Supported Env variables

For ⬛ NBBlackbox (main Django app):
- `NBBB_DB_HOST`: Hostname of the PostgreSQL database (default: "database")
- `NBBB_DB_PASSWD`: Database password (default: "secret")
- `NBBB_DB_USER`: Database user (default: "grader")
- `OIDC_RP_CLIENT_ID`: OIDC client ID for authentication
- `OIDC_RP_CLIENT_SECRET`: OIDC client secret
- `OIDC_RP_SIGN_ALGO`: OIDC signing algorithm (e.g. "RS256")
- `OIDC_OP_JWKS_ENDPOINT`: OIDC JWKS endpoint
- `OIDC_OP_AUTHORIZATION_ENDPOINT`: OIDC authorization endpoint
- `OIDC_OP_TOKEN_ENDPOINT`: OIDC token endpoint
- `OIDC_OP_USER_ENDPOINT`: OIDC user info endpoint
- `OIDC_OP_LOGOUT_ENDPOINT`: OIDC logout endpoint
- `OIDC_OP_LOGOUT_URL_METHOD`: Django method for logout (e.g. "portal.views.keycloak_logout")
- `EMAIL_HOST`: SMTP host for sending emails
- `NBBB_DEBUG`: Enable Django debug mode ("true"/"false")
- `NBBB_ALLOWED_HOSTS`: Comma-separated list of allowed hosts (default: "*")
- `RED_PERCENTAGE`: Lower threshold for red traffic light (default: "0.5")
- `YELLOW_PERCENTAGE`: Lower threshold for yellow traffic light (default: "0.7")
- `REQUEST_TIME_LIMIT`: Time in seconds between grading requests (default: "300")
- `LANGUAGE_CODE`: Default language code (default: "en")
- `MAINTENANCE_MODE`: (optional) Enable maintenance mode

For 👷 NBworker:
- `POSTGRES_HOST`: Hostname of the PostgreSQL database (default: "database")
- `POSTGRES_USER`: Database user (default: "grader")
- `POSTGRES_PASSWORD`: Database password (default: "secret")

### Running bare metal for developement

There are two ways of running the software throughout developement.
The first one is by using the docker-compose-dev compose file.
The second one is by running the database as a standalone docker container and the software directly.
First, create a dedicated network:
```docker network create broker```
To start a postgres docker container with the standard credential the software expects (Do not use these credentials in any prod deployments):
```docker run -d --name database --network broker -p 5432:5432 -e POSTGRES_PASSWORD=secret -e POSTGRES_USER=grader postgres``` 

Then, use the start script to create the superuser for django and start the server:
```NBBB_DEBUG=true NBBB_RUN_BAREMETAL=true ./start.sh```
The server will automatically reload if files change.

Finally, to allow the autograding of notebooks start a worker:
```docker run --name nbworker -e POSTGRES_HOST=database -e POSTGRES_USER=grader -e POSTGRES_PASSWORD=secret -v $(pwd)/testdata/source:/course/source --network broker registry.git.rwth-aachen.de/i5/teaching/dbis/nbgrader-blackbox/worker:latest```
Here, you can pull the image or build it via the dev compose (or manually ofc).

## Project structure

- `nbworker/`: Source code for the grading worker service (autograding, assignment sync, DB integration)
- `nbblackbox/`: Django project for the main web application (settings, URLs, WSGI/ASGI entrypoints)
- `grader/`: Django app with core logic for exercise management, grading, database models, views, and forms
- `docker-compose-dev.yaml`: Development docker-compose file for all services
- `Dockerfile`: Dockerfile for the main Django application
- `DockerfileWorker`: Dockerfile for the grading worker container
- `manage.py`: Django management tool (superuser, migrations, etc.)
- `start.sh`: Entrypoint script for running the main application in Docker