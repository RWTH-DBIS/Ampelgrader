# NBGrader Blackbox
A service for providing a student the possibility to preliminarily submit their notebooks to get an idea how they perfomed.
The service does not disclose the result of individual cells but rather only grouped into "subexercises".
The service consists mainly of two types of components, the main service, providing the web interface for both admin and students, and the nbworker, a script intended for
containerization, taking care of the grading of the notebooks.
These components communicate through a postgres database, the datamodel is documentated [here](datamodel.md).
## Features
- OIDC based authentication (e.g. for RWTH single sign on)
- Time restricted grading of notebooks
- coarse feedback which does not disclose details of mistakes made by the students
- auto processing of notebooks for easy creation of necessary metadata
- grading of high amounts of concurrent submitted notebooks by using a worker-based approach

## Workflow
Short summary of the idea of nbgrader:
1. The admin provides creates an exercise by providing the notebook for the students via ``/grader/autocreation`` or by manual creation.
2. Here, the admin configures are time window, in which grading of the exercise is allowed
3. A student who wishes to have a preliminary grading of their work submit the notebook to the service via the request form
4. The request grading process is stored in the database
5. One of the possible multiple workers, upon periodically checking the database, assigns the gradingprocess to itself by creating a corresponding entry in the workerassignment table
6. The worker grades the assignment and enters the results back into the database
7. The student is notified via email with the results / a link to the result page

## Getting Started
For developing, you can use the shipped 'docker-compose-dev.yaml' file, which defines all necessary configurations, such as the oidc provider and mounted volumes and the postgres database:

``docker-compose -f docker-compose-dev.yaml up``

### Preparing the jupyter notebooks

There are two ways for configuring the nb blackbox for notebooks.
The easier way is via the autocreation form, which parses the notebooks and looks for subexercise-tags of the form ``#subexercise:<LABEL>`` in the grading cells of nb-grader created notebooks.
The more complex way is to use the django-generated admin tools under /admin.

### Configuration

For configuration of the nbworker, see the [readme](nbworker/Readme.md).

#### Supported Env variables
- ALLOWED_HOSTS: comma seperated list of allowed hosts. Is passed to django allowed hosts setting (default: "127.0.0.1") 

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
- `nbworker/`: The source code of the worker script
- `nbblackbox/`: The source code of the main django page, mainly code created by django
- `grader/`: The grader application
- `Dockerfile`: The Dockerfile of the main application
- `DockerfileWorker`: The Dockerfile for creating the containerized worker
- `manage.py`: Django management tool, used for creating a superuser, running migrations etc.
- `start.sh`: Start script used for starting the main applicaiton inside a docker container
