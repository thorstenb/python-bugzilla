# rhbugzilla.py - a Python interface to Red Hat Bugzilla using xmlrpclib.
#
# Copyright (C) 2008-2012 Red Hat Inc.
# Author: Will Woods <wwoods@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import copy
import xmlrpclib

import bugzilla.base
from bugzilla import log
from bugzilla.bugzilla4 import Bugzilla42



class RHBugzilla(Bugzilla42):
    '''Concrete implementation of the Bugzilla protocol. This one uses the
    methods provided by Red Hat's Bugzilla 4.2+ instance, which is a superset
    of the Bugzilla 4.2 methods. The additional methods (e.g. Bug.update)
    should make their way into a later upstream Bugzilla release.

    Note that RHBZ4 *also* supports most of the old RHBZ methods, under the
    'bugzilla' namespace, so we use those when BZ4 methods aren't available.

    This class was written using bugzilla.redhat.com's API docs:
    https://bugzilla.redhat.com/docs/en/html/api/

    By default, _getbugs will multicall getBug(id) multiple times, rather than
    doing a single Bug.get(idlist) call. You can disable this behavior by
    setting the 'multicall' property to False. This will make it somewhat
    faster, but any missing/unreadable bugs will cause the entire call to
    Fault rather than returning any data.
    '''

    version = '0.1'

    def __init__(self, **kwargs):
        self.multicall = True
        if "multicall" in kwargs:
            self.multicall = kwargs.pop("multicall")

        Bugzilla42.__init__(self, **kwargs)

    #---- Methods and properties with basic bugzilla info

    def _multicall(self):
        '''This returns kind of a mash-up of the Bugzilla object and the
        xmlrpclib.MultiCall object. Methods you call on this object will be
        added to the MultiCall queue, but they will return None. When you're
        ready, call the run() method and all the methods in the queue will be
        run and the results of each will be returned in a list. So,
        for example:

        mc = bz._multicall()
        mc._getbug(1)
        mc._getbug(1337)
        mc._query({'component':'glibc', 'product':'Fedora', 'version':'devel'})
        (bug1, bug1337, queryresult) = mc.run()

        Note that you should only use the raw xmlrpc calls (mostly the methods
        starting with an underscore). Normal getbug(), for example, tries to
        return a _Bug object, but with the multicall object it'll end up empty
        and, therefore, useless.

        Further note that run() returns a list of raw xmlrpc results; you'll
        need to wrap the output in Bug objects yourself if you're doing that
        kind of thing. For example, Bugzilla.getbugs() could be implemented:

        mc = self._multicall()
        for id in idlist:
            mc._getbug(id)
        rawlist = mc.run()
        return [_Bug(self, dict=b) for b in rawlist]
        '''

        mc = copy.copy(self)
        mc._proxy = xmlrpclib.MultiCall(self._proxy)

        def run():
            return mc._proxy().results

        mc.run = run
        return mc

    # Connect the backend methods to the XMLRPC methods

    def _getqueryinfo(self):
        return self._proxy.bugzilla.getQueryInfo()

    #---- Methods for modifying existing bugs.

    # Most of these will probably also be available as Bug methods, e.g.:
    # Bugzilla.setstatus(id, status) ->
    #   Bug.setstatus(status): self.bugzilla.setstatus(self.bug_id, status)

    # TODO: update this when the XMLRPC interface grows requestee support
    def _updateflags(self, objid, flags):
        '''Updates the flags associated with a bug report.
        data should be a hash of {'flagname':'value'} pairs, like so:
        {'needinfo':'?', 'fedora-cvs':'+'}
        You may also add a "nomail":1 item, which will suppress email if set.

        NOTE: the Red Hat XMLRPC interface does not yet support setting the
        requestee (as in: needinfo from smartguy@answers.com). Alas.'''
        return self._proxy.bugzilla.updateFlags(objid, flags)

    #---- Methods for working with attachments

    # If your bugzilla wants attachments in something other than base64, you
    # should override _attachment_encode here.
    # If your bugzilla uses non-standard paths for attachment.cgi, you'll
    # want to override _attachment_uri here.

    def _attachfile(self, objid, **attachdata):
        return self._proxy.bugzilla.addAttachment(objid, attachdata)

    #---- createbug - call to create a new bug

    # Methods for updating a user
    def _updateperms(self, user, action, groups):
        r = self._proxy.bugzilla.updatePerms(user, action, groups, self.user,
                self.password)
        return r

    def _adduser(self, user, name):
        r = self._proxy.bugzilla.addUser(user, name, self.user, self.password)
        return r

    def _addcomponent(self, data):
        add_required_fields = ('product', 'component',
                               'initialowner', 'description')
        for field in add_required_fields:
            if field not in data or not data[field]:
                raise TypeError("mandatory fields missing: %s" % field)
        if type(data['product']) == int:
            data['product'] = self._product_id_to_name(data['product'])
        r = self._proxy.bugzilla.addComponent(data, self.user, self.password)
        return r

    def _editcomponent(self, data):
        edit_required_fields = ('initialowner', 'product', 'component')
        for field in edit_required_fields:
            if field not in data or not data[field]:
                raise TypeError("mandatory field missing: %s" % field)
        if type(data['product']) == int:
            data['product'] = self._product_id_to_name(data['product'])
        r = self._proxy.bugzilla.editComponent(data, self.user, self.password)
        return r

    def _getbugs(self, idlist):
        r = []
        if self.multicall:
            if len(idlist) == 1:
                return [self._proxy.bugzilla.getBug(idlist[0])]
            mc = self._multicall()
            for objid in idlist:
                mc._proxy.bugzilla.getBug(objid)
            raw_results = mc.run()
            del mc
            # check results for xmlrpc errors, and replace them with None
            r = bugzilla.base.replace_getbug_errors_with_None(raw_results)
        else:
            raw_results = self._proxy.Bug.get({'ids': idlist})
            r = [i for i in raw_results['bugs']]
        return r

    # This can be activated once Bug.get() returns all the data that
    # RHBZ's getBug() does.
    #_getbugs = Bugzilla3._getbugs # Also _getbug, _getbugsimple, etc.

    #---- Methods for updating bugs.

    def _add_bug_comment(self, ids, comment, is_private):
        '''Add a new comment to a specified bug ID(s). Returns the comment
        ID(s) array.
        '''

        ret = list()
        for objid in ids:
            r = self._proxy.Bug.add_comment({'id': objid, 'comment': comment,
                                             'is_private': is_private})
            if 'id' in r:
                ret.append(r['id'])

        return ret

    def _update_bugs(self, ids, updates):
        '''Update the given fields with the given data in one or more bugs.
        ids should be a list of integers or strings, representing bug ids or
        aliases.
        updates is a dict containing pairs like so: {'fieldname':'newvalue'}
        '''
        tmp = {"ids": ids}
        custom_fields = ["fixed_in"]

        for key, value in updates.items():
            if key in custom_fields:
                key = "cf_" + key
            tmp[key] = value

        return self._proxy.Bug.update(tmp)

    def _update_bug(self, objid, updates):
        '''
        Update a single bug, specified by integer ID or (string) bug alias.
        Really just a convenience method for _update_bugs(ids=[id], updates)
        '''
        return self._update_bugs(ids=[objid], updates=updates)

    # Eventually - when RHBugzilla is well and truly obsolete - we'll delete
    # all of these methods and refactor the Base Bugzilla object so all the bug
    # modification calls go through _update_bug.
    # Until then, all of these methods are basically just wrappers around it.

    # TODO: allow multiple bug IDs

    def _update_add_comment_fields(self, updatedict, comment, private):
        if not comment:
            return

        commentdict = {"body": comment}
        if private:
            commentdict["is_private"] = private
        updatedict["comment"] = commentdict

    def _setstatus(self, objid, status, comment='', private=False,
                   private_in_it=False, nomail=False):
        '''Set the status of the bug with the given ID.'''
        update = {'status': status}
        self._update_add_comment_fields(update, comment, private)

        return self._update_bug(objid, update)

    def _closebug(self, objid, resolution, dupeid, fixedin,
                  comment, isprivate, private_in_it, nomail):
        '''Close the given bug. This is the raw call, and no data checking is
        done here. That's up to the closebug method.
        Note that the private_in_it and nomail args are ignored.'''
        update = {'bug_status': 'CLOSED', 'resolution': resolution}
        if dupeid:
            update['resolution'] = 'DUPLICATE'
            update['dupe_of'] = dupeid
        if fixedin:
            update['fixed_in'] = fixedin
        self._update_add_comment_fields(update, comment, isprivate)

        return self._update_bug(objid, update)

    def _setassignee(self, objid, **data):
        '''Raw xmlrpc call to set one of the assignee fields on a bug.
        changeAssignment($id, $data, $username, $password)
        data: 'assigned_to', 'reporter', 'qa_contact', 'comment'
        returns: [$id, $mailresults]'''
        # drop empty items
        update = dict([(k, v) for k, v in data.iteritems() if (v and v != '')])
        return self._update_bug(objid, update)

    def _updatedeps(self, objid, blocked, dependson, action):
        '''Update the deps (blocked/dependson) for the given bug.
        blocked, dependson: list of bug ids/aliases
        action: 'add' or 'delete'
        '''
        if action not in ('add', 'delete', 'set'):
            raise ValueError("action must be 'add', 'set', or 'delete'")

        # change the action to be remove if it is delete
        if action == 'delete':
            action = 'remove'

        update = {
            'blocks': {action: blocked},
            'depends_on': {action: dependson}
        }
        self._update_bug(objid, update)

    def _updatecc(self, objid, cclist, action, comment='', nomail=False):
        '''Updates the CC list using the action and account list specified.
        cclist must be a list (not a tuple!) of addresses.
        action may be 'add', 'delete', or 'overwrite'.
        comment specifies an optional comment to add to the bug.
        if mail is True, email will be generated for this change.
        '''
        update = {}
        self._update_add_comment_fields(update, comment, False)

        if action in ('add', 'delete'):
            # Action 'delete' has been changed to 'remove' in Bugzilla 4.0+
            if action == 'delete':
                action = 'remove'

            update = {}
            update['cc'] = {}
            update['cc'][action] = cclist
            self._update_bug(objid, update)

        elif action == 'overwrite':
            r = self._getbug(objid)
            if 'cc' not in r:
                raise AttributeError("Can't find cc list in bug %s" %
                                     str(objid))
            self._updatecc(objid, r['cc'], 'delete')
            self._updatecc(objid, cclist, 'add')

        else:
            # XXX we don't check inputs on other backend methods, maybe this
            # is more appropriate in the public method(s)
            raise ValueError("action must be 'add', 'delete', or 'overwrite'")

    def _updatewhiteboard(self, objid, text, which, action, comment, private):
        '''Update the whiteboard given by 'which' for the given bug.
        performs the given action (which may be 'append', ' prepend', or
        'overwrite') using the given text.

        RHBZ3 Bug.update() only supports overwriting, so append/prepend
        may cause two server roundtrips - one to fetch, and one to update.
        '''
        if not which.endswith('_whiteboard'):
            which = which + '_whiteboard'

        update = {}
        if action == 'overwrite':
            update[which] = text

        else:
            r = self._getbug(objid)
            if which not in r:
                raise ValueError("No such whiteboard %s in bug %s" %
                                 (which, str(objid)))
            wb = r[which]
            if action == 'prepend':
                update[which] = text + ' ' + wb
            elif action == 'append':
                update[which] = wb + ' ' + text

        self._update_add_comment_fields(update, comment, private)
        self._update_bug(objid, update)


    #################
    # Query methods #
    #################

    def pre_translation(self, query):
        '''Translates the query for possible aliases'''
        if 'bug_id' in query:
            if type(query['bug_id']) is not list:
                query['id'] = query['bug_id'].split(',')
            else:
                query['id'] = query['bug_id']
            del query['bug_id']

        if 'component' in query:
            if type(query['component']) is not list:
                query['component'] = query['component'].split(',')

        if 'include_fields' not in query and 'column_list' not in query:
            return

        if 'include_fields' not in query:
            query['include_fields'] = list()
            if 'column_list' in query:
                query['include_fields'] = query['column_list']
                del query['column_list']

        include_fields = query['include_fields']
        for newname, oldname in self.field_aliases:
            if oldname in include_fields:
                include_fields.remove(oldname)
                if newname not in include_fields:
                    include_fields.append(newname)

    def post_translation(self, query, bug):
        '''Translates the query result'''
        tmpstr = []
        if 'flags' in bug:
            for tmp in bug['flags']:
                tmpstr.append("%s%s" % (tmp['name'], tmp['status']))

            bug['flags'] = ",".join(tmpstr)
        if 'blocks' in bug:
            if len(bug['blocks']) > 0:
                bug['blockedby'] = ','.join([str(b) for b in bug['blocks']])
                bug['blocked'] = ','.join([str(b) for b in bug['blocks']])
            else:
                bug['blockedby'] = ''
                bug['blocked'] = ''
        if 'keywords' in bug:
            if len(bug['keywords']) > 0:
                bug['keywords'] = ','.join(bug['keywords'])
            else:
                bug['keywords'] = ''
        if 'component' in bug:
            # we have to emulate the old behavior and add 'components' as
            # list instead
            bug['components'] = bug['component']
            bug['component'] = bug['component'][0]
        if 'alias' in bug:
            if len(bug['alias']) > 0:
                bug['alias'] = ','.join(bug['alias'])
            else:
                bug['alias'] = ''
        if 'groups' in bug:
            # groups went to the opposite direction: it got simpler
            # instead of having name, ison, description, it's now just
            # an array of strings of the groups the bug belongs to
            # we're emulating the old behaviour here
            tmp = list()
            for g in bug['groups']:
                t = {}
                t['name'] = g
                t['description'] = g
                t['ison'] = 1
                tmp.append(t)
            bug['groups'] = tmp

    def build_query(self, **kwargs):
        query = {}

        def add_email(key, count):
            if not key in kwargs:
                return count

            value = kwargs.get(key)
            del(kwargs[key])
            if value is None:
                return count

            query["query_format"] = "advanced"
            query['email%i' % count] = value
            query['email%s%i' % (key, count)] = True
            query['emailtype%i' % count] = kwargs.get("emailtype", "substring")
            return count + 1

        def bool_smart_split(boolval):
            # This parses the CLI command syntax, but we only want to
            # do space splitting if the space is actually part of a
            # boolean operator
            boolchars = ["|", "&", "!"]
            add = ""
            retlist = []

            for word in boolval.split(" "):
                if word.strip() in boolchars:
                    word = word.strip()
                    if add:
                        retlist.append(add)
                        add = ""
                    retlist.append(word)
                else:
                    if add:
                        add += " "
                    add += word

            if add:
                retlist.append(add)
            return retlist

        def add_boolean(kwkey, key, bool_id):
            if not kwkey in kwargs:
                return bool_id

            value = kwargs.get(kwkey)
            del(kwargs[kwkey])
            if value is None:
                return bool_id

            query["query_format"] = "advanced"
            for boolval in value:
                and_count = 0
                or_count = 0

                def make_bool_str(prefix):
                    return "%s%i-%i-%i" % (prefix, bool_id,
                                           and_count, or_count)

                for par in bool_smart_split(boolval):
                    field = None
                    fval = par
                    typ = kwargs.get("booleantype", "substring")

                    if par == "&":
                        and_count += 1
                    elif par == "|":
                        or_count += 1
                    elif par == "!":
                        query['negate%i' % bool_id] = 1
                    elif not key:
                        if par.find('-') == -1:
                            raise RuntimeError('Malformed boolean query: %s' %
                                               value)

                        args = par.split('-', 2)
                        field = args[0]
                        typ = args[1]
                        fval = None
                        if len(args) == 3:
                            fval = args[2]
                    else:
                        field = key

                    query[make_bool_str("field")] = field
                    if fval:
                        query[make_bool_str("value")] = fval
                    query[make_bool_str("type")] = typ

                bool_id += 1
            return bool_id

        # Use fancy email specification for RH bugzilla. It isn't
        # strictly required, but is more powerful, and it is what
        # bin/bugzilla historically generated. This requires
        # query_format='advanced' which is an RHBZ only XMLRPC extension
        email_count = 1
        email_count = add_email("cc", email_count)
        email_count = add_email("assigned_to", email_count)
        email_count = add_email("reporter", email_count)
        email_count = add_email("qa_contact", email_count)

        chart_id = 0
        chart_id = add_boolean("fixed_in", "cf_fixed_in", chart_id)
        chart_id = add_boolean("blocked", "blocked", chart_id)
        chart_id = add_boolean("dependson", "dependson", chart_id)
        chart_id = add_boolean("flag", "flagtypes.name", chart_id)
        chart_id = add_boolean("qa_whiteboard", "cf_qa_whiteboard", chart_id)
        chart_id = add_boolean("devel_whiteboard", "cf_devel_whiteboard",
                               chart_id)
        chart_id = add_boolean("alias", "alias", chart_id)
        chart_id = add_boolean("boolean_query", None, chart_id)

        newquery = Bugzilla42.build_query(self, **kwargs)
        query.update(newquery)
        self.pre_translation(query)
        return query

    def _query(self, query):
        '''Query bugzilla and return a list of matching bugs.
        query must be a dict with fields like those in in querydata['fields'].
        You can also pass in keys called 'quicksearch' or 'savedsearch' -
        'quicksearch' will do a quick keyword search like the simple search
        on the Bugzilla home page.
        'savedsearch' should be the name of a previously-saved search to
        execute. You need to be logged in for this to work.
        Returns a dict like this: {'bugs':buglist,
                                   'sql':querystring}
        buglist is a list of dicts describing bugs, and 'sql' contains the SQL
        generated by executing the search.
        You can also pass 'limit:[int]' to limit the number of results.
        For more info, see:
        http://www.bugzilla.org/docs/4.0/en/html/api/Bugzilla/
        '''
        old = query.copy()
        self.pre_translation(query)

        if old != query:
            log.debug("RHBugzilla altered query to: %s", query)

        ret = self._proxy.Bug.search(query)

        # Unfortunately we need a hack to preserve backwards
        # compabibility with older RHBZ
        for bug in ret['bugs']:
            self.post_translation(query, bug)

        return ret


# Just for API back compat
class RHBugzilla3(RHBugzilla):
    pass


class RHBugzilla4(RHBugzilla):
    pass
