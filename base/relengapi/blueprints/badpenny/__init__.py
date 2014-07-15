# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from relengapi import db
import wsme.types
import logging
import datetime
import sqlalchemy as sa
from flask import json
from flask import url_for
from flask import Blueprint
from flask import render_template
from relengapi import p
from relengapi import apimethod
from relengapi.lib import permissions
from relengapi.lib import angular
from relengapi.lib import api
from werkzeug.exceptions import NotFound

logger = logging.getLogger(__name__)
bp = Blueprint('badpenny', __name__,
               static_folder='static',
               template_folder='templates')

p.base.badpenny.view.doc('See scheduled tasks and logs of previous jobs')


def permitted():
    return permissions.can(p.base.badpenny.view)
bp.root_widget_template(
    'badpenny_root_widget.html', priority=100, condition=permitted)


class BadpennyJob(db.declarative_base('relengapi')):
    __tablename__ = 'badpenny_jobs'

    id = sa.Column(sa.Integer, primary_key=True)
    task_id = sa.Column(sa.Integer, sa.ForeignKey('badpenny_tasks.id'))
    task = sa.orm.relationship('BadpennyTask')

    created_at = sa.Column(sa.DateTime(), nullable=False)
    started_at = sa.Column(sa.DateTime(), nullable=True)
    completed_at = sa.Column(sa.DateTime(), nullable=True)
    successful = sa.Column(sa.Boolean())

    # 'result' is JSON data
    result = sa.Column(sa.Text())

    # 'logs' is free-form, hopefully brief, log text
    logs = sa.Column(sa.Text())

    def to_jsonjob(self):
        return JsonJob(id=self.id,
                       task_name=self.task.name,
                       created_at=self.created_at,
                       started_at=self.started_at,
                       completed_at=self.completed_at,
                       successful=self.successful,
                       result=self.result,
                       logs=self.logs)


class JsonJob(wsme.types.Base):

    """A job is a single occurrence of a task."""

    _name = "BadpennyJob"

    #: unique job id
    id = wsme.types.wsattr(int, mandatory=True)
    task_name = wsme.types.wsattr(unicode, mandatory=True)
    created_at = wsme.types.wsattr(datetime.datetime, mandatory=True)
    started_at = wsme.types.wsattr(datetime.datetime, mandatory=False)
    completed_at = wsme.types.wsattr(datetime.datetime, mandatory=False)
    successful = wsme.types.wsattr(bool, mandatory=False)
    result = wsme.types.wsattr(unicode, mandatory=False)
    logs = wsme.types.wsattr(unicode, mandatory=False)


class BadpennyTask(db.declarative_base('relengapi'), db.UniqueMixin):
    __tablename__ = 'badpenny_tasks'

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.Text, nullable=False)

    # all other data about a task is determined from runtime information (that
    # is, from the decorated function itself)

    jobs = sa.orm.relationship('BadpennyJob')

    @property
    def last_success(self):
        # TODO: get this value as part of the DB query for the task
        job = BadpennyJob.query. \
            filter(BadpennyJob.task_id == self.id). \
            order_by(sa.desc(BadpennyJob.created_at)). \
            limit(1). \
            first()
        if not job:
            return -1
        elif job.successful:
            return 1
        else:
            return 0

    @classmethod
    def unique_filter(cls, query, name):
        return query.filter(BadpennyTask.name == name)

    @classmethod
    def unique_hash(cls, name):
        return name

    def to_jsontask(self, with_jobs=False):
        t = JsonTask(name=self.name, last_success=self.last_success)
        if with_jobs:
            t.jobs = [j.to_jsonjob() for j in self.jobs]
        return t


class JsonTask(wsme.types.Base):

    """A task describes an operation that occurs periodically."""

    _name = "BadpennyTask"

    #: unique task name (based on the qualified Python function name)
    name = wsme.types.wsattr(unicode, mandatory=True)

    #: last success of the task: -1 (never run), 0 (failed), or 1 (succeeded)
    last_success = wsme.types.wsattr(int, mandatory=True)

    #: all recent jobs for this task; this is only returned when a single task
    # is requested.
    jobs = wsme.types.wsattr([JsonJob], mandatory=False)

    # TODO: schedule, active, etc. -- taken from runtime config


@bp.route('/')
@p.base.badpenny.view.require()
def root():
    return angular.template('badpenny.html',
                            url_for('.static', filename='badpenny.js'),
                            url_for('.static', filename='badpenny.css'),
                            tasks=api.get_data(list_tasks))


@bp.route('/tasks')
@apimethod([JsonTask])
@p.base.badpenny.view.require()
def list_tasks():
    """List all badpenny tasks."""
    return [t.to_jsontask() for t in BadpennyTask.query.all()]


@bp.route('/tasks/<task_name>')
@apimethod(JsonTask, unicode)
@p.base.badpenny.view.require()
def get_task(task_name):
    """Get information on a badpenny task by name"""
    t = BadpennyTask.query.filter(BadpennyTask.name == task_name).first()
    if not t:
        raise NotFound
    return t.to_jsontask(with_jobs=True)


@bp.route('/jobs')
@apimethod([JsonJob])
@p.base.badpenny.view.require()
def list_jobs():
    """List all badpenny jobs."""
    return [t.to_jsonjob() for t in BadpennyJob.query.all()]


@bp.route('/jobs/<job_id>')
@apimethod(JsonJob, int)
@p.base.badpenny.view.require()
def get_job(job_id):
    """Get information on a badpenny task by name"""
    j = BadpennyJob.query.filter(BadpennyJob.id == job_id).first()
    if not j:
        raise NotFound
    return j.to_jsonjob()
