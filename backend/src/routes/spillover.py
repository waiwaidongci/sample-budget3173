from fastapi import APIRouter, Depends
from fastapi.responses import Response
from src.config.database import get_db
from src.middlewares.auth import current_user, writer
from src.schemas.spillover import (SubmissionInput, UploadInput, CorrectionInput, SpilloverRunInput)
from src.controllers import spillover as ctrl
router = APIRouter()

@router.get('/spillover/studies/{study_id}/submissions')
def list_submissions(study_id: int, db=Depends(get_db), user=Depends(current_user)):
    return ctrl.list_submissions(db, study_id)

@router.post('/spillover/submissions')
def create_submission(data: SubmissionInput, db=Depends(get_db), user=Depends(writer)):
    return ctrl.create_submission(db, data, user)

@router.post('/spillover/uploads')
def upload(data: UploadInput, db=Depends(get_db), user=Depends(writer)):
    return ctrl.upload(db, data, user)

@router.get('/spillover/submissions/{submission_id}/completeness')
def completeness(submission_id: int, db=Depends(get_db), user=Depends(current_user)):
    return ctrl.completeness(db, submission_id)

@router.post('/spillover/corrections')
def correction(data: CorrectionInput, db=Depends(get_db), user=Depends(writer)):
    return ctrl.submit_correction(db, data, user)

@router.get('/spillover/studies/{study_id}/corrections')
def list_corrections(study_id: int, db=Depends(get_db), user=Depends(current_user)):
    return ctrl.list_corrections(db, study_id)

@router.post('/spillover/runs')
def create_run(data: SpilloverRunInput, db=Depends(get_db), user=Depends(writer)):
    return ctrl.create_run(db, data, user)

@router.get('/spillover/runs')
def list_runs(study_id: int | None = None, db=Depends(get_db), user=Depends(current_user)):
    return ctrl.list_runs(db, study_id)

@router.get('/spillover/runs/{run_id}')
def get_run(run_id: int, db=Depends(get_db), user=Depends(current_user)):
    return ctrl.get_run(db, run_id)

@router.get('/spillover/runs/{run_id}/export')
def export_run(run_id: int, db=Depends(get_db), user=Depends(current_user)):
    return Response(content=ctrl.export_run(db, run_id, user).encode('utf-8'), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="spillover-{run_id}.csv"'})
