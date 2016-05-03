# Copyright 2016 Splunk, Inc.
#
# Licensed under the Apache License, Version 2.0 (the 'License'): you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

'''
Splunk user access control related utilities.
'''

import re
import json
import logging

from splunklib import binding

from solnlib.utils import retry
import solnlib.splunk_rest_client as rest_client

__all__ = ['ObjectACL',
           'ObjectACLManagerException',
           'ObjectACLManager',
           'AppCapabilityManagerException',
           'AppCapabilityManager',
           'UserAccessException',
           'CheckUserAccess',
           'get_current_username',
           'get_user_capabilities',
           'user_is_capable',
           'get_user_roles']


class ObjectACL(object):
    OBJ_COLLECTION_KEY = 'obj_collection'
    OBJ_ID_KEY = 'obj_id'
    OBJ_TYPE_KEY = 'obj_type'
    OBJ_APP_KEY = 'obj_app'
    OBJ_OWNER_KEY = 'obj_owner'
    OBJ_PERMS_KEY = 'obj_perms'
    OBJ_PERMS_READ_KEY = 'read'
    OBJ_PERMS_WRITE_KEY = 'write'
    OBJ_PERMS_DELETE_KEY = 'delete'
    OBJ_PERMS_ALLOW_ALL = '*'
    OBJ_SHARED_BY_INCLUSION_KEY = 'obj_shared_by_inclusion'

    def __init__(self, obj_collection, obj_id, obj_type,
                 obj_app, obj_owner, obj_perms, obj_shared_by_inclusion):
        '''Object ACL record.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_id: ID of this object.
        :type obj_id: ``string``
        :param obj_app: App of this object.
        :param obj_type: ``string``
        :param obj_owner: Owner of this object.
        :param obj_owner: ``string``
        :param obj_perms: Object perms, like: {
            'read': ['*'],
            'write': ['admin'],
            'delete': ['admin']}.
        :type obj_perms: ``dict``
        :param obj_shared_by_inclusion: Flag of object is shared by inclusion.
        :type obj_shared_by_inclusion: ``bool``

        Usage::

           >>> from solnlib import user_access
           >>> obj_acl = user_access.ObjectACL(
           >>>    'test_collection',
           >>>    '9defa6f510d711e6be16a45e60e34295',
           >>>    'test_object',
           >>>    'Splunk_TA_test',
           >>>    'admin',
           >>>    {'read': ['*'], 'write': ['admin'], 'delete': ['admin']},
           >>>    False)
        '''

        self._obj_collection = obj_collection
        self._obj_id = obj_id
        self._obj_type = obj_type
        self._obj_app = obj_app
        self._obj_owner = obj_owner
        self._obj_perms = obj_perms
        self._obj_shared_by_inclusion = obj_shared_by_inclusion

    @property
    def obj_collection(self):
        return self._obj_collection

    @obj_collection.setter
    def obj_collection(self, obj_collection):
        self._obj_collection = obj_collection

    @property
    def obj_id(self):
        return self._obj_id

    @obj_id.setter
    def obj_id(self, obj_id):
        self._obj_id = obj_id

    @property
    def obj_type(self):
        return self._obj_type

    @obj_type.setter
    def obj_type(self, obj_type):
        self._obj_type = obj_type

    @property
    def obj_app(self):
        return self._obj_app

    @obj_app.setter
    def obj_app(self, obj_app):
        self._obj_app = obj_app

    @property
    def obj_owner(self):
        return self._obj_owner

    @obj_owner.setter
    def obj_owner(self, obj_owner):
        self._obj_owner = obj_owner

    @property
    def obj_perms(self):
        return self._obj_perms

    @obj_perms.setter
    def obj_perms(self, obj_perms):
        self._obj_perms = obj_perms

    @property
    def obj_shared_by_inclusion(self):
        return self._obj_shared_by_inclusion

    @obj_shared_by_inclusion.setter
    def obj_shared_by_inclusion(self, obj_shared_by_inclusion):
        self._obj_shared_by_inclusion = obj_shared_by_inclusion

    @property
    def record(self):
        '''Get object acl record.

        :returns: Object acl record, like: {
            '_key': 'test_collection-1234',
            'obj_collection': 'test_collection',
            'obj_id': '1234',
            'obj_type': 'test_object',
            'obj_app': 'Splunk_TA_test',
            'obj_owner': 'admin',
            'obj_perms': {'read': ['*'], 'write': ['admin'], 'delete': ['admin']},
            'obj_shared_by_inclusion': false}
        :rtype: ``dict``
        '''

        return {
            '_key': self.generate_key(self._obj_collection, self._obj_id),
            self.OBJ_COLLECTION_KEY: self._obj_collection,
            self.OBJ_ID_KEY: self._obj_id,
            self.OBJ_TYPE_KEY: self._obj_type,
            self.OBJ_APP_KEY: self._obj_app,
            self.OBJ_OWNER_KEY: self._obj_owner,
            self.OBJ_PERMS_KEY: {
                self.OBJ_PERMS_READ_KEY: self._obj_perms[
                    self.OBJ_PERMS_READ_KEY],
                self.OBJ_PERMS_WRITE_KEY: self._obj_perms[
                    self.OBJ_PERMS_WRITE_KEY],
                self.OBJ_PERMS_DELETE_KEY: self._obj_perms[
                    self.OBJ_PERMS_DELETE_KEY]
            },
            self.OBJ_SHARED_BY_INCLUSION_KEY: self._obj_shared_by_inclusion
        }

    @staticmethod
    def generate_key(obj_collection, obj_id):
        return '{obj_collection}_{obj_id}'.format(
            obj_collection=obj_collection, obj_id=obj_id)

    @staticmethod
    def parse(obj_acl):
        return ObjectACL(
            obj_acl[ObjectACL.OBJ_COLLECTION_KEY],
            obj_acl[ObjectACL.OBJ_ID_KEY],
            obj_acl[ObjectACL.OBJ_TYPE_KEY],
            obj_acl[ObjectACL.OBJ_APP_KEY],
            obj_acl[ObjectACL.OBJ_OWNER_KEY],
            obj_acl[ObjectACL.OBJ_PERMS_KEY],
            obj_acl[ObjectACL.OBJ_SHARED_BY_INCLUSION_KEY])

    def merge(self, obj_acl):
        for perm_key in self._obj_perms:
            self._obj_perms[perm_key] = list(
                set.union(
                    set(self._obj_perms[perm_key]),
                    set(obj_acl._obj_perms[perm_key])))
            if self.OBJ_PERMS_ALLOW_ALL in self._obj_perms[perm_key]:
                self._obj_perms[perm_key] = [self.OBJ_PERMS_ALLOW_ALL]

    def __str__(self):
        return json.dumps(self.record)


@retry(exceptions=[binding.HTTPError])
def _get_collection_data(collection_name, session_key, app, owner,
                         scheme, host, port, **context):
    kvstore = rest_client.SplunkRestClient(session_key,
                                           app,
                                           owner=owner,
                                           scheme=scheme,
                                           host=host,
                                           port=port,
                                           **context).kvstore

    collection_name = re.sub(r'[^\w]+', '_', collection_name)
    try:
        kvstore.get(name=collection_name)
    except binding.HTTPError as e:
        if e.status != 404:
            raise

        kvstore.create(collection_name)

    collections = kvstore.list(search=collection_name)
    for collection in collections:
        if collection.name == collection_name:
            return collection.data
    else:
        raise KeyError('Get collection data: %s failed.' % collection_name)


class ObjectACLManagerException(object):
    pass


class ObjectACLManager(object):
    '''Object ACL manager.

    :param collection_name: Collection name to store object ACL info.
    :type collection_name: ``string``
    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param app: App name of namespace.
    :type app: ``string``
    :param owner: (optional) Owner of namespace, default is `nobody`.
    :type owner: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``

    :raises ObjectACLManagerException: If init ObjectACLManager failed.

    Usage::

       >>> from solnlib import user_access
       >>> oaclm = user_access.ObjectACLManager(session_key,
                                                'Splunk_TA_test')
    '''

    def __init__(self, collection_name, session_key, app, owner='nobody',
                 scheme='https', host='localhost', port=8089, **context):
        collection_name = '{app}_{collection_name}'.format(
            app=app, collection_name=collection_name)
        try:
            self._collection_data = _get_collection_data(
                collection_name, session_key, app, owner,
                scheme, host, port, **context)
        except KeyError:
            raise ObjectACLManagerException(
                'Get object acl collection: %s fail.' % collection_name)

    def update_acl(self, obj_collection, obj_id, obj_type, obj_app, obj_owner,
                   obj_perms, obj_shared_by_inclusion, replace_existing=True):
        '''Update acl info of object.

        Construct a new object acl info first, if `replace_existing` is True
        then replace existing acl info else merge new object acl info with the
        old one and replace the old acl info with merged acl info.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_id: ID of this object.
        :type obj_id: ``string``
        :param obj_app: App of this object.
        :param obj_type: ``string``
        :param obj_owner: Owner of this object.
        :param obj_owner: ``string``
        :param obj_perms: Object perms, like: {
            'read': ['*'],
            'write': ['admin'],
            'delete': ['admin']}.
        :type obj_perms: ``dict``
        :param obj_shared_by_inclusion: Flag of object is shared by inclusion.
        :type obj_shared_by_inclusion: ``bool``
        :param replace_existing: (optional) Replace existing acl info flag, True
            indicates replace old acl info with new one else merge with old acl
            info, default is True.
        :type replace_existing: ``bool``
        '''

        obj_acl = ObjectACL(
            obj_collection, obj_id, obj_type,
            obj_app, obj_owner, obj_perms, obj_shared_by_inclusion)

        if not replace_existing:
            try:
                old_obj_acl = self.get_acl(obj_collection, obj_id)
            except binding.HTTPError as e:
                if e.status != 404:
                    raise

                old_obj_acl = None

            if old_obj_acl:
                obj_acl.merge(old_obj_acl)

        self._collection_data.batch_save(obj_acl.record)

    def update_acls(self, obj_collection, obj_ids, obj_type, obj_app, obj_owner,
                    obj_perms, obj_shared_by_inclusion, replace_existing=True):
        '''Batch update acl info of objects.

        :param obj_collection: Collection where objects currently stored.
        :type obj_collection: ``string``
        :param obj_id: IDs list of objects.
        :type obj_id: ``list``
        :param obj_app: App of this object.
        :param obj_type: ``string``
        :param obj_owner: Owner of this object.
        :param obj_owner: ``string``
        :param obj_perms: Object perms, like: {
            'read': ['*'],
            'write': ['admin'],
            'delete': ['admin']}.
        :type obj_perms: ``dict``
        :param obj_shared_by_inclusion: Flag of object is shared by inclusion.
        :type obj_shared_by_inclusion: ``bool``
        :param replace_existing: (optional) Replace existing acl info flag, True
            indicates replace old acl info with new one else merge with old acl
            info, default is True.
        :type replace_existing: ``bool``
        '''

        obj_acl_records = []
        for obj_id in obj_ids:
            obj_acl = ObjectACL(
                obj_collection, obj_id, obj_type,
                obj_app, obj_owner, obj_perms, obj_shared_by_inclusion)

            if not replace_existing:
                try:
                    old_obj_acl = self.get_acl(obj_collection, obj_id)
                except binding.HTTPError as e:
                    if e.status == 404:
                        old_obj_acl = None
                    else:
                        raise

                if old_obj_acl:
                    obj_acl.merge(old_obj_acl)

            obj_acl_records.append(obj_acl.record)

        self._collection_data.batch_save(*obj_acl_records)

    def get_acl(self, obj_collection, obj_id):
        '''Get acl info.

        Query object acl info with parameter of the combination of
        `obj_collection` and `obj_id` from `self.collection_name` and
        return it.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_id: ID of this object.
        :type obj_id: ``string``
        :returns: Object acl info if success else None.
        :rtype: ``ObjectACL``
        '''

        key = ObjectACL.generate_key(obj_collection, obj_id)
        obj_acl = self._collection_data.query_by_id(key)

        return ObjectACL.parse(obj_acl)

    def get_acls(self, obj_collection, obj_ids):
        '''Batch get acl info.

        Query objects acl info with parameter of the combination of
        `obj_collection` and `obj_ids` from KVStore and return them.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_ids: IDs of objects.
        :type obj_ids: ``list``
        :returns: List of `ObjectACL` instances.
        :rtype: ``list``
        '''

        query = json.dumps(
            {'$or': [{'_key': ObjectACL.generate_key(obj_collection, obj_id)}
                     for obj_id in obj_ids]})
        obj_acls = self._collection_data.query(query=query)

        return [ObjectACL.parse(obj_acl) for obj_acl in obj_acls]

    def delete_acl(self, obj_collection, obj_id):
        '''Delete acl info.

        Query object acl info with parameter of the combination of
        `obj_collection` and `obj_ids` from KVStore and delete it.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_id: ID of this object.
        :type obj_id: ``string``
        '''

        key = ObjectACL.generate_key(obj_collection, obj_id)
        self._collection_data.delete_by_id(key)

    def delete_acls(self, obj_collection, obj_ids):
        '''Batch delete acl info.

        Query objects acl info with parameter of the combination of
        `obj_collection` and `obj_ids` from KVStore and delete them.

        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_ids: IDs of objects.
        :type obj_id: ``list``
        '''

        query = json.dumps(
            {'$or': [{'_key': ObjectACL.generate_key(obj_collection, obj_id)}
                     for obj_id in obj_ids]})
        self._collection_data.delete(query=query)

    def get_accessible_object_ids(self, user, operation, obj_collection, obj_ids):
        '''Get accessible IDs of objects from `obj_acls`.

        :param user: User name of current `operation`.
        :type user: ``string``
        :param operation: User operation, possible option: (read/write/delete).
        :type operation: ``string``
        :param obj_collection: Collection where object currently stored.
        :type obj_collection: ``string``
        :param obj_ids: IDs of objects.
        :type obj_id: ``list``
        :returns: List of IDs of accessible objects.
        :rtype: ``list``
        '''

        obj_acls = self.get_acls(obj_collection, obj_ids)
        accessible_obj_ids = []
        for obj_acl in obj_acls:
            perms = obj_acl.obj_perms[operation]
            if ObjectACL.OBJ_PERMS_ALLOW_ALL in perms or user in perms:
                accessible_obj_ids.append(obj_acl.obj_id)

        return accessible_obj_ids


class AppCapabilityManagerException(Exception):
    pass


class AppCapabilityManager(object):
    '''App capability manager.

    :param collection_name: Collection name to store capabilities.
    :type collection_name: ``string``
    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param app: App name of namespace.
    :type app: ``string``
    :param owner: (optional) Owner of namespace, default is `nobody`.
    :type owner: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``

    :raises AppCapabilityManagerException: If init AppCapabilityManager failed.

    Usage::

       >>> from solnlib import user_access
       >>> acm = user_access.AppCapabilityManager('test_collection',
                                                  session_key,
                                                  'Splunk_TA_test')
       >>> acm.register_capabilities(...)
       >>> acm.unregister_capabilities(...)
    '''

    def __init__(self, collection_name, session_key, app, owner='nobody',
                 scheme='https', host='localhost', port=8089, **context):
        self._app = app

        collection_name = '{app}_{collection_name}'.format(
            app=app, collection_name=collection_name)
        try:
            self._collection_data = _get_collection_data(
                collection_name, session_key, app, owner,
                scheme, host, port, **context)
        except KeyError:
            raise AppCapabilityManagerException(
                'Get app capabilities collection: %s failed.' %
                collection_name)

    def register_capabilities(self, capabilities):
        '''Register app capabilities.

        :param capabilities: App capabilities, example: {
            'object_type1': {
            'read': 'read_app_object_type1',
            'write': 'write_app_object_type1',
            'delete': 'delete_app_object_type1'},
            'object_type2': {
            'read': 'read_app_object_type2',
            'write': 'write_app_object_type2',
            'delete': 'delete_app_object_type2'},
            ...}
        :type capabilities: ``dict``
        '''

        record = {'_key': self._app, 'capabilities': capabilities}
        self._collection_data.batch_save(record)

    def unregister_capabilities(self):
        '''Unregister app capabilities.
        '''

        self._collection_data.delete_by_id(self._app)

    def capabilities_are_registered(self):
        '''Check if app capabilities are registered.

        :returns: True if app capabilities are registered else
            False.
        :rtype: ``bool``
        '''

        try:
            self._collection_data.query_by_id(self._app)
        except binding.HTTPError:
            return False

        return True

    def get_capabilities(self):
        '''Get app capabilities.

        :returns: App capabilities.
        :rtype: ``dict``
        '''

        record = self._collection_data.query_by_id(self._app)
        return record['capabilities']


class UserAccessException(Exception):
    pass


class CheckUserAccess(object):
    '''Decorator for handling user access.

    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param username: User name of roles to get.
    :type username: ``string``
    :param capabilities: App capabilities, example: {
        'object_type1': {
        'read': 'read_app_object_type1',
        'write': 'write_app_object_type1',
        'delete': 'delete_app_object_type1'},
        'object_type2': {
        'read': 'read_app_object_type2',
        'write': 'write_app_object_type2',
        'delete': 'delete_app_object_type2'},
        ...}
    :type capabilities: ``dict``
    :param obj_type: Object type.
    :type obj_type: ``string``
    :param operation: User operation, possible option: (read/write/delete).
    :type operation: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``

    Usage::
       >>> from solnlib.user_access import CheckUserAccess
       >>> @CheckUserAccess(session_key, username, capabilities, 'test_object', 'read')
       >>> def fun():
       >>>    ...
    '''

    def __init__(self, session_key, username, capabilities, obj_type, operation,
                 scheme='https', host='localhost', port=8089, **context):
        self._session_key = session_key
        self._username = username
        self._capabilities = capabilities
        self._obj_type = obj_type
        self._operation = operation
        self._scheme = scheme
        self._host = host
        self._port = port
        self._context = context

    def __call__(self, f):
        def wrapper(*args, **kwargs):
            is_capable = False

            if self._obj_type is None:
                self._obj_type = kwargs.get('object')
            if self._obj_type is None:
                raise UserAccessException(
                    'Expecting non-empty `obj_type` to check user access.')

            owner = kwargs.get('owner')
            if owner is None:
                logging.warn(
                    'No `owner` is detected, no ownership based checks will be enforced.')
            elif self._username == owner:
                is_capable = True

            if not is_capable:
                capability = \
                    self._capabilities[self._obj_type][self._operation]
                is_capable = user_is_capable(
                    self._session_key, self._username, capability,
                    scheme=self._scheme, host=self._host, port=self._port, **self._context)

            if is_capable:
                return f(*args, **kwargs)
            else:
                raise UserAccessException(
                    'Permission denied, %s does not have the capability: %s.' %
                    (self._username, capability))

        return wrapper


def get_current_username(session_key,
                         scheme='https', host='localhost', port=8089, **context):
    '''Get current user name from `session_key`.

    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``
    :returns: Current user name.
    :rtype: ``string``

    Usage::

       >>> from solnlib import user_access
       >>> user_name = user_access.get_current_username(session_key)
    '''

    context = rest_client.SplunkRestClient(
        session_key,
        '-',
        scheme=scheme,
        host=host,
        port=port,
        **context)
    response = context.get('/services/authentication/current-context',
                           output_mode='json').body.read()
    return json.loads(response)['entry'][0]['content']['username']


def get_user_capabilities(session_key, username,
                          scheme='https', host='localhost', port=8089, **context):
    '''Get user capabilities.

    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param username: User name of capabilities to get.
    :type username: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``
    :returns: User capabilities.
    :rtype: ``list``

    Usage::

       >>> from solnlib import user_access
       >>> user_capabilities = user_access.get_user_capabilities(
       >>>     session_key, 'test_user')
    '''

    context = rest_client.SplunkRestClient(
        session_key,
        '-',
        scheme=scheme,
        host=host,
        port=port,
        **context)
    url = '/services/authentication/users/{username}'.format(username=username)
    response = context.get(url, output_mode='json').body.read()
    return json.loads(response)['entry'][0]['content']['capabilities']


def user_is_capable(session_key, username, capability,
                    scheme='https', host='localhost', port=8089, **context):
    '''Check if user is capable for given `capability`.

    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param username: (optional) User name of roles to get.
    :type username: ``string``
    :param capability: The capability we wish to check for.
    :type capability: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``
    :returns: True if user is capable else False.
    :rtype: ``bool``

    Usage::

       >>> from solnlib import user_access
       >>> is_capable = user_access.user_is_capable(
       >>>     session_key, 'test_user', 'object_read_capability')
    '''

    capabilities = get_user_capabilities(
        session_key, username, scheme=scheme, host=host, port=port, **context)
    return capability in capabilities


def get_user_roles(session_key, username,
                   scheme='https', host='localhost', port=8089, **context):
    '''Get user roles.

    :param session_key: Splunk access token.
    :type session_key: ``string``
    :param username: (optional) User name of roles to get.
    :type username: ``string``
    :param scheme: (optional) The access scheme, default is `https`.
    :type scheme: ``string``
    :param host: (optional) The host name, default is `localhost`.
    :type host: ``string``
    :param port: (optional) The port number, default is 8089.
    :type port: ``integer``
    :param context: Other configurations for Splunk rest client.
    :type context: ``dict``
    :returns: User roles.
    :rtype: ``list``

    Usage::

       >>> from solnlib import user_access
       >>> user_roles = user_access.get_user_roles(session_key, 'test_user')
    '''

    context = rest_client.SplunkRestClient(
        session_key,
        '-',
        scheme=scheme,
        host=host,
        port=port,
        **context)
    url = '/services/authentication/users/{username}'.format(username=username)
    response = context.get(url, output_mode='json').body.read()
    return json.loads(response)['entry'][0]['content']['roles']
