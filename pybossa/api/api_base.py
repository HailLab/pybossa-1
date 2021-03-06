# -*- coding: utf8 -*-
# This file is part of PYBOSSA.
#
# Copyright (C) 2015 Scifabric LTD.
#
# PYBOSSA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PYBOSSA is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with PYBOSSA.  If not, see <http://www.gnu.org/licenses/>.
"""
PYBOSSA api module for exposing domain objects via an API.

This package adds GET, POST, PUT and DELETE methods for any class:
    * projects,
    * tasks,
    * task_runs,
    * users,
    * etc.

"""
import json
from flask import request, abort, Response
from flask.ext.login import current_user
from flask.views import MethodView
from werkzeug.exceptions import NotFound, Unauthorized, Forbidden
from pybossa.util import jsonpify, fuzzyboolean
from pybossa.core import ratelimits
from pybossa.auth import ensure_authorized_to
from pybossa.hateoas import Hateoas
from pybossa.ratelimit import ratelimit
from pybossa.error import ErrorStatus
from pybossa.core import project_repo, user_repo, task_repo, result_repo, blog_repo
from pybossa.model import DomainObject

repos = {'Task'   : {'repo': task_repo, 'filter': 'filter_tasks_by',
                     'get': 'get_task', 'save': 'save', 'update': 'update',
                     'delete': 'delete'},
        'TaskRun' : {'repo': task_repo, 'filter': 'filter_task_runs_by',
                     'get': 'get_task_run',  'save': 'save', 'update': 'update',
                     'delete': 'delete'},
        'User'    : {'repo': user_repo, 'filter': 'filter_by', 'get': 'get',
                     'save': 'save', 'update': 'update'},
        'Project' : {'repo': project_repo, 'filter': 'filter_by',
                      'context': 'filter_owner_by', 'get': 'get',
                      'save': 'save', 'update': 'update', 'delete': 'delete'},
        'Category': {'repo': project_repo, 'filter': 'filter_categories_by',
                     'get': 'get_category', 'save': 'save_category',
                     'update': 'update_category', 'delete': 'delete_category'},
        'Result':   {'repo': result_repo, 'filter': 'filter_by', 'get': 'get',
                     'update': 'update'},
        'Blogpost': {'repo': blog_repo, 'filter': 'filter_by', 'get': 'get',
                     'update': 'update', 'save': 'save', 'delete': 'delete'}
        }


error = ErrorStatus()


class APIBase(MethodView):

    """Class to create CRUD methods."""

    hateoas = Hateoas()

    def valid_args(self):
        """Check if the domain object args are valid."""
        for k in request.args.keys():
            if k not in ['api_key']:
                getattr(self.__class__, k)

    def options(self, **kwargs):  # pragma: no cover
        """Return '' for Options method."""
        return ''

    @jsonpify
    @ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
    def get(self, oid):
        """Get an object.

        Returns an item from the DB with the request.data JSON object or all
        the items if oid == None

        :arg self: The class of the object to be retrieved
        :arg integer oid: the ID of the object in the DB
        :returns: The JSON item/s stored in the DB

        """
        try:
            ensure_authorized_to('read', self.__class__)
            query = self._db_query(oid)
            json_response = self._create_json_response(query, oid)
            return Response(json_response, mimetype='application/json')
        except Exception as e:
            return error.format_exception(
                e,
                target=self.__class__.__name__.lower(),
                action='GET')

    def _create_json_response(self, query_result, oid):
        if len(query_result) == 1 and query_result[0] is None:
            raise abort(404)
        items = []
        for result in query_result:
            # This is for n_favs orderby case
            if not isinstance(result, DomainObject):
                result = result[0]
            try:
                if (result.__class__ != self.__class__):
                    (item, headline, rank) = result
                else:
                    item = result
                    headline = None
                    rank = None
                datum = self._create_dict_from_model(item)
                if headline:
                    datum['headline'] = headline
                if rank:
                    datum['rank'] = rank
                ensure_authorized_to('read', item)
                items.append(datum)
            except (Forbidden, Unauthorized):
                # Remove last added item, as it is 401 or 403
                if len(items) > 0:
                    items.pop()
            except Exception:  # pragma: no cover
                raise
        if oid is not None:
            ensure_authorized_to('read', query_result[0])
            items = items[0]
        return json.dumps(items)

    def _create_dict_from_model(self, model):
        return self._select_attributes(self._add_hateoas_links(model))

    def _add_hateoas_links(self, item):
        obj = item.dictize()
        related = request.args.get('related')
        if related:
            if item.__class__.__name__ == 'Task':
                obj['task_runs'] = []
                obj['result'] = None
                task_runs = task_repo.filter_task_runs_by(task_id=item.id)
                results = result_repo.filter_by(task_id=item.id, last_version=True)
                for tr in task_runs:
                    obj['task_runs'].append(tr.dictize())
                for r in results:
                    obj['result'] = r.dictize()

            if item.__class__.__name__ == 'TaskRun':
                tasks = task_repo.filter_tasks_by(id=item.task_id)
                results = result_repo.filter_by(task_id=item.task_id, last_version=True)
                obj['task'] = None
                obj['result'] = None
                for t in tasks:
                    obj['task'] = t.dictize()
                for r in results:
                    obj['result'] = r.dictize()

            if item.__class__.__name__ == 'Result':
                tasks = task_repo.filter_tasks_by(id=item.task_id)
                task_runs = task_repo.filter_task_runs_by(task_id=item.task_id)
                obj['task_runs'] = []
                for t in tasks:
                    obj['task'] = t.dictize()
                for tr in task_runs:
                    obj['task_runs'].append(tr.dictize())

        links, link = self.hateoas.create_links(item)
        if links:
            obj['links'] = links
        if link:
            obj['link'] = link
        return obj

    def _db_query(self, oid):
        """Returns a list with the results of the query"""
        repo_info = repos[self.__class__.__name__]
        if oid is None:
            limit, offset, orderby = self._set_limit_and_offset()
            results = self._filter_query(repo_info, limit, offset, orderby)
        else:
            repo = repo_info['repo']
            query_func = repo_info['get']
            results = [getattr(repo, query_func)(oid)]
        return results

    def api_context(self, all_arg, **filters):
        if current_user.is_authenticated():
            filters['owner_id'] = current_user.id
        if filters.get('owner_id') and all_arg == '1':
            del filters['owner_id']
        return filters

    def _filter_query(self, repo_info, limit, offset, orderby):
        filters = {}
        for k in request.args.keys():
            if k not in ['limit', 'offset', 'api_key', 'last_id', 'all',
                         'fulltextsearch', 'desc', 'orderby', 'related']:
                # Raise an error if the k arg is not a column
                getattr(self.__class__, k)
                filters[k] = request.args[k]
        repo = repo_info['repo']
        filters = self.api_context(all_arg=request.args.get('all'), **filters)
        query_func = repo_info['filter']
        filters = self._custom_filter(filters)
        last_id = request.args.get('last_id')
        fulltextsearch = request.args.get('fulltextsearch')
        desc = request.args.get('desc') if request.args.get('desc') else False
        desc = fuzzyboolean(desc)
        if last_id:
            results = getattr(repo, query_func)(limit=limit, last_id=last_id,
                                                fulltextsearch=fulltextsearch,
                                                desc=False,
                                                orderby=orderby,
                                                **filters)
        else:
            results = getattr(repo, query_func)(limit=limit, offset=offset,
                                                fulltextsearch=fulltextsearch,
                                                desc=desc,
                                                orderby=orderby,
                                                **filters)
        return results

    def _set_limit_and_offset(self):
        try:
            limit = min(100, int(request.args.get('limit')))
        except (ValueError, TypeError):
            limit = 20
        try:
            offset = int(request.args.get('offset'))
        except (ValueError, TypeError):
            offset = 0
        try:
            orderby = request.args.get('orderby') if request.args.get('orderby') else 'id'
        except (ValueError, TypeError):
            orderby = 'updated'
        return limit, offset, orderby

    @jsonpify
    @ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
    def post(self):
        """Post an item to the DB with the request.data JSON object.

        :arg self: The class of the object to be inserted
        :returns: The JSON item stored in the DB

        """
        try:
            self.valid_args()
            data = json.loads(request.data)
            self._forbidden_attributes(data)
            inst = self._create_instance_from_request(data)
            repo = repos[self.__class__.__name__]['repo']
            save_func = repos[self.__class__.__name__]['save']
            getattr(repo, save_func)(inst)
            self._log_changes(None, inst)
            return json.dumps(inst.dictize())
        except Exception as e:
            return error.format_exception(
                e,
                target=self.__class__.__name__.lower(),
                action='POST')

    def _create_instance_from_request(self, data):
        data = self.hateoas.remove_links(data)
        inst = self.__class__(**data)
        self._update_object(inst)
        ensure_authorized_to('create', inst)
        self._validate_instance(inst)
        return inst

    @jsonpify
    @ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
    def delete(self, oid):
        """Delete a single item from the DB.

        :arg self: The class of the object to be deleted
        :arg integer oid: the ID of the object in the DB
        :returns: An HTTP status code based on the output of the action.

        More info about HTTP status codes for this action `here
        <http://www.w3.org/Protocols/rfc2616/rfc2616-sec9.html#sec9.7>`_.

        """
        try:
            self.valid_args()
            self._delete_instance(oid)
            return '', 204
        except Exception as e:
            return error.format_exception(
                e,
                target=self.__class__.__name__.lower(),
                action='DELETE')

    def _delete_instance(self, oid):
        repo = repos[self.__class__.__name__]['repo']
        query_func = repos[self.__class__.__name__]['get']
        inst = getattr(repo, query_func)(oid)
        if inst is None:
            raise NotFound
        ensure_authorized_to('delete', inst)
        self._log_changes(inst, None)
        delete_func = repos[self.__class__.__name__]['delete']
        getattr(repo, delete_func)(inst)
        return inst

    @jsonpify
    @ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
    def put(self, oid):
        """Update a single item in the DB.

        :arg self: The class of the object to be updated
        :arg integer oid: the ID of the object in the DB
        :returns: An HTTP status code based on the output of the action.

        More info about HTTP status codes for this action `here
        <http://www.w3.org/Protocols/rfc2616/rfc2616-sec9.html#sec9.6>`_.

        """
        try:
            self.valid_args()
            inst = self._update_instance(oid)
            return Response(json.dumps(inst.dictize()), 200,
                            mimetype='application/json')
        except Exception as e:
            return error.format_exception(
                e,
                target=self.__class__.__name__.lower(),
                action='PUT')

    def _update_instance(self, oid):
        repo = repos[self.__class__.__name__]['repo']
        query_func = repos[self.__class__.__name__]['get']
        existing = getattr(repo, query_func)(oid)
        if existing is None:
            raise NotFound
        ensure_authorized_to('update', existing)
        data = json.loads(request.data)
        self._forbidden_attributes(data)
        # Remove hateoas links
        data = self.hateoas.remove_links(data)
        # may be missing the id as we allow partial updates
        data['id'] = oid
        self.__class__(**data)
        old = self.__class__(**existing.dictize())
        for key in data:
            setattr(existing, key, data[key])
        self._update_attribute(existing, old)
        update_func = repos[self.__class__.__name__]['update']
        self._validate_instance(existing)
        getattr(repo, update_func)(existing)
        self._log_changes(old, existing)
        return existing

    def _update_object(self, data_dict):
        """Update object.

        Method to be overriden in inheriting classes which wish to update
        data dict.

        """
        pass

    def _update_attribute(self, new, old):
        """Update object attribute if new value is passed.
        Method to be overriden in inheriting classes which wish to update
        data dict.

        """

    def _select_attributes(self, item_data):
        """Method to be overriden in inheriting classes in case it is not
        desired that every object attribute is returned by the API.
        """
        return item_data

    def _custom_filter(self, query):
        """Method to be overriden in inheriting classes which wish to consider
        specific filtering criteria.
        """
        return query

    def _validate_instance(self, instance):
        """Method to be overriden in inheriting classes which may need to
        validate the creation (POST) or modification (PUT) of a domain object
        for reasons other than business logic ones (e.g. overlapping of a
        project name witht a URL).
        """
        pass

    def _log_changes(self, old_obj, new_obj):
        """Method to be overriden by inheriting classes for logging purposes"""
        pass

    def _forbidden_attributes(self, data):
        """Method to be overriden by inheriting classes that will not allow for
        certain fields to be used in PUT or POST requests"""
        pass
