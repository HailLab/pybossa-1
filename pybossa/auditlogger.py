# -*- coding: utf8 -*-
# This file is part of PyBossa.
#
# Copyright (C) 2014 SF Isle of Man Limited
#
# PyBossa is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PyBossa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with PyBossa.  If not, see <http://www.gnu.org/licenses/>.

from pybossa.model.auditlog import Auditlog

class AuditLogger(object):

    def __init__(self, auditlog_repo, caller='web'):
        self.repo = auditlog_repo
        self.caller = caller

    def log_event(self, app, user, action, attribute, old_value, new_value):
        log = Auditlog(
            app_id=app.id,
            app_short_name=app.short_name,
            user_id=user.id,
            user_name=user.name,
            action=action,
            caller=self.caller,
            attribute=attribute,
            old_value=old_value,
            new_value=new_value)
        self.repo.save(log)

    def get_project_logs(self, project_id):
        return self.repo.filter_by(app_id=project_id)


    def add_log_entry(self, old_project, new_project, user):
        if old_project is None:
            self.log_event(new_project, user, 'create', 'project',
                           'Nothing', 'New project')
            return
        if new_project is None:
            self.log_event(old_project, user, 'delete', 'project', 'Saved', 'Deleted')
            return
        old = old_project.dictize()
        new = new_project.dictize()
        attributes = (set(old.keys()) | set(new.keys())) - set(['updated'])
        changes = {}
        for attr in attributes:
            if old.get(attr) != new.get(attr):
                changes[attr] = (old.get(attr), new.get(attr))
        for attr in changes:
            if changes[attr][0] is None and attr == 'info':
                old_value = {}
                new_value = changes[attr][1]
                self._manage_info_keys(new_project, user,
                                       old_value, new_value, 'update')
            else:
                old_value = changes[attr][0]
                new_value = changes[attr][1]
                if attr == 'info':
                    self._manage_info_keys(new_project, user,
                                           old_value, new_value, 'update')
                else:
                    if old_value is None or '':
                        old_value = ''
                    if new_value is None or '':
                        new_value = ''
                    if (unicode(old_value) != unicode(new_value)):
                        self.log_event(new_project, user, 'update', attr,
                                       old_value, new_value)


    def _manage_info_keys(self, project, user, old_value, new_value, action):
        s_o = set(old_value.keys())
        s_n = set(new_value.keys())

        # For new keys
        for new_key in (s_n - s_o):
            # only log changed keys
            if old_value.get(new_key) == new_value.get(new_key):
                continue
            self.log_event(project, user, action, new_key,
                           old_value.get(new_key),
                           new_value.get(new_key))
        # For updated keys
        for same_key in (s_n & s_o):
            # only log changed keys
            if old_value.get(same_key) == new_value.get(same_key):
                continue
            self.log_event(project, user, action, same_key,
                           old_value.get(same_key),
                           new_value.get(same_key))
