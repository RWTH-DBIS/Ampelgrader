# NB Blackbox data model
**This is for overview only, when in doubt always refer to the schema defined in grader/model.py**
```mermaid
---
title: NB Blackbox ER
---

erDiagram
    Exercise {
        string identifier PK
        date startDate
        date stopDate
    }
    Notebook {
        string filename PK
        string inExercise FK
    }
    
    SubExercise {
        integer id PK
        string innotebook FK
    }
    
    Cell {
        string cellId PK
        integer maxScore
        integer subExercise FK
    }
    
    GradingProcess {
        uuid identifier
        string forEmail
        string exercise FK
        date requestedAt
    }
    
    Grading {
        uuid processid FK
        string cellId
        integer grade
    }
    
    ErrorLog {
        uuid processid FK,PK
        string log
    }
    
    WorkerAssignment {
        uuid worker_id PK
        date assigned_at
        uuid process FK
    }
    
    StudentNotebook {
        BLOB data
        string notebook FK
        uuid process FK
    }
        
    Exercise ||--|| Notebook: has
    GradingProcess }|--|| Exercise: for
    GradingProcess ||--|{ Grading: hasGrading
    GradingProcess ||--o| ErrorLog: hasError
    
    Grading ||--|| Cell: hasGrade

    Notebook ||--o{ SubExercise: hasExercises
    SubExercise ||--|{ Cell: hasCells

    GradingProcess ||--o| WorkerAssignment: assigned
    StudentNotebook }o--|| Notebook: upload
    StudentNotebook |o--|| GradingProcess: process
```
