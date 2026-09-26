from app.constants.statuses import (
    JobStatus,
    is_valid_job_transition,
)


def test_valid_state_transitions():
    assert is_valid_job_transition(JobStatus.QUEUED, JobStatus.RUNNING) is True
    assert is_valid_job_transition(JobStatus.RUNNING, JobStatus.PROCESSING) is True
    assert is_valid_job_transition(JobStatus.PROCESSING, JobStatus.DONE) is True
    assert is_valid_job_transition(JobStatus.PROCESSING, JobStatus.FAILED) is True
    assert is_valid_job_transition(JobStatus.FAILED, JobStatus.RETRYING) is True
    assert is_valid_job_transition(JobStatus.RETRYING, JobStatus.QUEUED) is True
    assert is_valid_job_transition(JobStatus.QUEUED, JobStatus.CANCELLED) is True


def test_invalid_state_transitions():
    assert is_valid_job_transition(JobStatus.DONE, JobStatus.QUEUED) is False
    assert is_valid_job_transition(JobStatus.CANCELLED, JobStatus.RUNNING) is False
    assert is_valid_job_transition(JobStatus.QUEUED, JobStatus.DONE) is False
