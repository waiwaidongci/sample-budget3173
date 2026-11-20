from pydantic import BaseModel,Field

class SubmissionInput(BaseModel):
    study_id:int=Field(gt=0)
    batch_code:str=Field(min_length=1,max_length=100)
    note:str=Field(default='',max_length=2000)

class UploadInput(BaseModel):
    study_id:int=Field(gt=0)
    batch_code:str=Field(min_length=1,max_length=100)
    kind:str=Field(min_length=2,max_length=20)
    filename:str=Field(min_length=1,max_length=120)
    content:str=Field(min_length=1,max_length=8_000_000)

class CorrectionInput(BaseModel):
    study_id:int=Field(gt=0)
    batch_code:str=Field(min_length=1,max_length=100)
    person_id:str=Field(min_length=1,max_length=64)
    source_filename:str=Field(min_length=1,max_length=120)
    payload:dict

class SpilloverRunInput(BaseModel):
    study_id:int=Field(gt=0)
    submission_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    parameters:dict=Field(default_factory=dict)
