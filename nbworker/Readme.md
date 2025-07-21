# NBWorker
The nbworker script is responsible for automatically retrieving ungraded exercises from the database and grade them.
For this it uses the API of Nbgrader.

Each worker is identified with a randomly generated UUID.

The worker checks the database periodically for ungraded exercise submissions.
If one is found, it enters itself into the database as assigned worker.
After grading the assignment using nbgrader API.autograde() call, it accesses nbgraders database via the gradebook api object, to extract the points for each cell.
These points are then entered into the database.
## Configuration

### General
***WAITING_TIME***: The time the worker waits inbetween checks for ungraded exercises

**COURSE_DIRECTORY**: The root directory of the course used as a template for grading (default: /course)

**DUMMY_STUDENT_ID**: The id of the dummy student which is used for nbgrader (default "d")

### Database
The worker assumes the schema as defined in ../grader/models.py present in the database.

The following environment variables are supported for configuration of the database access:

**POSTGRES_HOST**: The url of the Postgres database

**POSTGRES_PORT**: The port of the Postgres database

**POSTGRES_USER**: The User used to connect to the database

**POSTGRES_PASSWORD**: The password used to connect to the database

**POSTGRES_DB**: The database which is used

