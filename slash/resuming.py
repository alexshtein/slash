import os
import logbook
from sqlalchemy import Column, DateTime, String, Boolean, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from datetime import datetime

_RESUME_DIR = os.path.expanduser("~/.slash/session_states")
_DB_NAME = 'resume_state.db'
_logger = logbook.Logger(__name__)
Base = declarative_base()
session = sessionmaker()
is_db_initialized = False

class ResumeState(Base):
    __tablename__ = 'resume_state'
    id = Column(Integer, primary_key=True)
    session_id = Column(String, nullable=False)
    test_name = Column(String, nullable=False)
    needs_rerun = Column(Boolean, nullable=False)

class SessionMetadata(Base):
    __tablename__ = 'session_metadata'
    session_id = Column(String, primary_key=True)
    src_folder = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)

def init_db():
    engine = create_engine('sqlite:///{0}/{1}'.format(_RESUME_DIR, _DB_NAME))
    session.configure(bind=engine)
    Base.metadata.create_all(engine)

@contextmanager
def connecting_to_db():
    global is_db_initialized
    if not is_db_initialized:
        init_db()
        is_db_initialized = True
    new_session = session()
    try:
        yield new_session
        new_session.commit()
    except:
        raise
    finally:
        new_session.close()

def save_resume_state(session_result, conn):
    metadata = SessionMetadata(
                    session_id=session_result.session.id,
                    src_folder=os.getcwd(),
                    created_at=datetime.now())
    conn.add(metadata)
    session_tests = [
                ResumeState(
                    session_id=session_result.session.id,
                    test_name=str(result.test_metadata.address),
                    needs_rerun=result.is_failure() or result.is_error() or not result.is_started()
                )
                for result in session_result.iter_test_results()
            ]
    conn.add_all(session_tests)
    _logger.debug('Saved resume state to DB')

def get_last_resumeable_session_id(conn):
    current_folder = os.getcwd()
    session_id = conn.query(SessionMetadata).filter(SessionMetadata.src_folder == current_folder).order_by(SessionMetadata.created_at.desc()).first()
    if not session_id:
        raise CannotResume("No sessions found for folder {0}".format(current_folder))
    return session_id.session_id

def get_tests_to_resume(session_id, conn):
    session_tests = conn.query(ResumeState).filter(ResumeState.session_id == session_id).all()
    if not session_tests:
        raise CannotResume("Could not find resume data for session {0}".format(session_id))
    return [test.test_name for test in session_tests if test.needs_rerun]

class CannotResume(Exception):
    pass
