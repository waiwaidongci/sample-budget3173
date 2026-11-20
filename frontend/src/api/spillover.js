import {request,post} from './client.js';
export const spillover={
  submissions:sid=>request(`/spillover/studies/${sid}/submissions`),
  createSubmission:x=>post('/spillover/submissions',x),
  upload:x=>post('/spillover/uploads',x),
  completeness:id=>request(`/spillover/submissions/${id}/completeness`),
  corrections:sid=>request(`/spillover/studies/${sid}/corrections`),
  submitCorrection:x=>post('/spillover/corrections',x),
  runs:sid=>request(`/spillover/runs${sid?`?study_id=${sid}`:''}`),
  createRun:x=>post('/spillover/runs',x),
  getRun:id=>request(`/spillover/runs/${id}`),
  exportRun:id=>request(`/spillover/runs/${id}/export`),
};
