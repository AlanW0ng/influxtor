# coding:utf-8

import json
import urllib

from tornado.gen import coroutine, Return
from influxdb.line_protocol import make_lines, quote_ident, quote_literal
from influxdb.resultset import ResultSet
from tornado.httpclient import AsyncHTTPClient, HTTPRequest


class InfluxDBClientError(Exception):
    """Raised when an error occurs in the request."""
    def __init__(self, content, code=None):
        if isinstance(content, type(b'')):
            content = content.decode('UTF-8', 'replace')

        if code is not None:
            message = "%s: %s" % (code, content)
        else:
            message = content

        super(InfluxDBClientError, self).__init__(
            message
        )
        self.content = content
        self.code = code


class InfluxDBServerError(Exception):
    """Raised when a server error occurs."""
    def __init__(self, content):
        super(InfluxDBServerError, self).__init__(content)

class InfluxDBClient(object):

    def __init__(self,
                 host='localhost',
                 port=8086,
                 username='root',
                 password='root',
                 database=None,
                 ssl=False,
                 verify_ssl=False,
                 ):
        self.__host = host
        self.__port = int(port)
        self._username = username
        self._password = password
        self._database = database
        self._verify_ssl = verify_ssl
        self._scheme = "http"
        if ssl is True:
            self._scheme = "https"
        self.__baseurl = "{0}://{1}:{2}".format(
            self._scheme,
            self._host,
            self._port)

        self._headers = {
            'Content-type': 'application/json',
            'Accept': 'text/plain'
        }

    @property
    def _baseurl(self):
        return self._get_baseurl()

    def _get_baseurl(self):
        return self.__baseurl

    @property
    def _host(self):
        return self._get_host()

    def _get_host(self):
        return self.__host

    @property
    def _port(self):
        return self._get_port()

    def _get_port(self):
        return self.__port

    def switch_database(self, database):
        """Change the client's database.

        :param database: the name of the database to switch to
        :type database: str
        """
        self._database = database

    def switch_user(self, username, password):
        """Change the client's username.

        :param username: the username to switch to
        :type username: str
        :param password: the password for the username
        :type password: str
        """
        self._username = username
        self._password = password

    @coroutine
    def write_points(self,
                     points,
                     time_precision=None,
                     database=None,
                     retention_policy=None,
                     tags=None,
                     batch_size=None,
                     protocol='json'
                     ):
        if batch_size and batch_size > 0:
            for batch in self._batches(points, batch_size):
                yield self._write_points(points=batch,
                                   time_precision=time_precision,
                                   database=database,
                                   retention_policy=retention_policy,
                                   tags=tags, protocol=protocol)
            raise Return(True)
        else:
            ret = yield self._write_points(points=points,
                                      time_precision=time_precision,
                                      database=database,
                                      retention_policy=retention_policy,
                                      tags=tags, protocol=protocol)
            raise Return(ret)

    def _batches(self, iterable, size):
        for i in xrange(0, len(iterable), size):
            yield iterable[i:i + size]

    @coroutine
    def request(self, url, method='GET', params=None, data=None,
                expected_response_code=200, headers=None):
        url = "{0}/{1}".format(self._baseurl, url)

        if headers is None:
            headers = self._headers
        _params = {}
        if self._username and self._password:
            _params["u"] = self._username
            _params["p"] = self._password

        if params is not None:
            for k in params:
                _k, _v = k, params[k]
                if isinstance(_k,unicode):
                    _k = _k.endcode("utf-8")
                if isinstance(_v,unicode):
                    _v = _v.encode("utf-8")
                _params[_k] = _v
        if _params:
            url += "?" + urllib.urlencode(_params)

        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        http_client = AsyncHTTPClient()
        request = HTTPRequest(url,
                              method=method,
                              headers=headers,
                              body=data,
                              validate_cert=self._verify_ssl)
        response = yield http_client.fetch(request)

        if 500 <= response.code < 600:
            raise InfluxDBServerError(response.error)
        elif response.code == expected_response_code:
            raise Return(response)
        else:
            raise InfluxDBClientError(response.error, response.code)

    @coroutine
    def query(self,
              query,
              params=None,
              epoch=None,
              expected_response_code=200,
              database=None,
              raise_errors=True):
        """Send a query to InfluxDB.

        :param query: the actual query string
        :type query: str

        :param params: additional parameters for the request, defaults to {}
        :type params: dict

        :param expected_response_code: the expected status code of response,
            defaults to 200
        :type expected_response_code: int

        :param database: database to query, defaults to None
        :type database: str

        :param raise_errors: Whether or not to raise exceptions when InfluxDB
            returns errors, defaults to True
        :type raise_errors: bool

        :returns: the queried data
        :rtype: :class:`~.ResultSet`
        """
        if params is None:
            params = {}

        params['q'] = query
        params['db'] = database or self._database

        if epoch is not None:
            params['epoch'] = epoch

        response = yield self.request(
            url="query",
            method='GET',
            params=params,
            data=None,
            expected_response_code=expected_response_code
        )

        data = json.loads(response.body)

        results = [
            ResultSet(result, raise_errors=raise_errors)
            for result
            in data.get('results', [])
        ]

        # TODO(aviau): Always return a list. (This would be a breaking change)
        if len(results) == 1:
            raise Return(results[0])
        else:
            raise Return(results)

    @coroutine
    def write(self, data, params=None, expected_response_code=204,
              protocol='json'):
        """Write data to InfluxDB.

        :param data: the data to be written
        :type data: (if protocol is 'json') dict
                    (if protocol is 'line') sequence of line protocol strings
        :param params: additional parameters for the request, defaults to None
        :type params: dict
        :param expected_response_code: the expected response code of the write
            operation, defaults to 204
        :type expected_response_code: int
        :param protocol: protocol of input data, either 'json' or 'line'
        :type protocol: str
        :returns: True, if the write operation is successful
        :rtype: bool
        """

        headers = self._headers
        headers['Content-type'] = 'application/octet-stream'

        if params:
            precision = params.get('precision')
        else:
            precision = None

        if protocol == 'json':
            data = make_lines(data, precision).encode('utf-8')
        elif protocol == 'line':
            data = ('\n'.join(data) + '\n').encode('utf-8')

        yield self.request(
            url="write",
            method='POST',
            params=params,
            data=data,
            expected_response_code=expected_response_code,
            headers=headers
        )
        raise Return(True)

    @coroutine
    def _write_points(self,
                      points,
                      time_precision,
                      database,
                      retention_policy,
                      tags,
                      protocol='json'):
        if time_precision not in ['n', 'u', 'ms', 's', 'm', 'h', None]:
            raise ValueError(
                "Invalid time precision is given. "
                "(use 'n', 'u', 'ms', 's', 'm' or 'h')")

        if protocol == 'json':
            data = {
                'points': points
            }

            if tags is not None:
                data['tags'] = tags
        else:
            data = points

        params = {
            'db': database or self._database
        }

        if time_precision is not None:
            params['precision'] = time_precision

        if retention_policy is not None:
            params['rp'] = retention_policy

        yield self.write(
                data=data,
                params=params,
                expected_response_code=204,
                protocol=protocol
            )

        raise Return(True)

    @coroutine
    def get_list_database(self):
        """Get the list of databases in InfluxDB.

        :returns: all databases in InfluxDB
        :rtype: list of dictionaries

        :Example:

        ::

            >> dbs = client.get_list_database()
            >> dbs
            [{u'name': u'db1'}, {u'name': u'db2'}, {u'name': u'db3'}]
        """
        ret = yield self.query("SHOW DATABASES")
        raise Return(list(ret.get_points()))

    @coroutine
    def create_database(self, dbname):
        """Create a new database in InfluxDB.

        :param dbname: the name of the database to create
        :type dbname: str
        """
        yield self.query("CREATE DATABASE \"%s\"" % dbname)

    @coroutine
    def drop_database(self, dbname):
        """Drop a database from InfluxDB.

        :param dbname: the name of the database to drop
        :type dbname: str
        """
        yield self.query("DROP DATABASE \"%s\"" % dbname)

    @coroutine
    def create_retention_policy(self, name, duration, replication,
                                database=None, default=False):
        """Create a retention policy for a database.

        :param name: the name of the new retention policy
        :type name: str
        :param duration: the duration of the new retention policy.
            Durations such as 1h, 90m, 12h, 7d, and 4w, are all supported
            and mean 1 hour, 90 minutes, 12 hours, 7 day, and 4 weeks,
            respectively. For infinite retention – meaning the data will
            never be deleted – use 'INF' for duration.
            The minimum retention period is 1 hour.
        :type duration: str
        :param replication: the replication of the retention policy
        :type replication: str
        :param database: the database for which the retention policy is
            created. Defaults to current client's database
        :type database: str
        :param default: whether or not to set the policy as default
        :type default: bool
        """
        query_string = \
            "CREATE RETENTION POLICY \"%s\" ON \"%s\" " \
            "DURATION %s REPLICATION %s" % \
            (name, database or self._database, duration, replication)

        if default is True:
            query_string += " DEFAULT"

        yield self.query(query_string)

    @coroutine
    def alter_retention_policy(self, name, database=None,
                               duration=None, replication=None, default=None):
        """Mofidy an existing retention policy for a database.

        :param name: the name of the retention policy to modify
        :type name: str
        :param database: the database for which the retention policy is
            modified. Defaults to current client's database
        :type database: str
        :param duration: the new duration of the existing retention policy.
            Durations such as 1h, 90m, 12h, 7d, and 4w, are all supported
            and mean 1 hour, 90 minutes, 12 hours, 7 day, and 4 weeks,
            respectively. For infinite retention – meaning the data will
            never be deleted – use 'INF' for duration.
            The minimum retention period is 1 hour.
        :type duration: str
        :param replication: the new replication of the existing
            retention policy
        :type replication: str
        :param default: whether or not to set the modified policy as default
        :type default: bool

        .. note:: at least one of duration, replication, or default flag
            should be set. Otherwise the operation will fail.
        """
        query_string = (
            "ALTER RETENTION POLICY {0} ON {1}"
        ).format(quote_ident(name), quote_ident(database or self._database))
        if duration:
            query_string += " DURATION {0}".format(duration)
        if replication:
            query_string += " REPLICATION {0}".format(replication)
        if default is True:
            query_string += " DEFAULT"

        yield self.query(query_string)

    @coroutine
    def drop_retention_policy(self, name, database=None):
        """Drop an existing retention policy for a database.

        :param name: the name of the retention policy to drop
        :type name: str
        :param database: the database for which the retention policy is
            dropped. Defaults to current client's database
        :type database: str
        """
        query_string = (
            "DROP RETENTION POLICY {0} ON {1}"
        ).format(quote_ident(name), quote_ident(database or self._database))
        yield self.query(query_string)

    @coroutine
    def get_list_retention_policies(self, database=None):
        """Get the list of retention policies for a database.

        :param database: the name of the database, defaults to the client's
            current database
        :type database: str
        :returns: all retention policies for the database
        :rtype: list of dictionaries

        :Example:

        ::

            >> ret_policies = client.get_list_retention_policies('my_db')
            >> ret_policies
            [{u'default': True,
              u'duration': u'0',
              u'name': u'default',
              u'replicaN': 1}]
            """
        rsp = yield self.query(
            "SHOW RETENTION POLICIES ON \"%s\"" % (database or self._database)
        )
        raise Return(list(rsp.get_points()))

    @coroutine
    def get_list_users(self):
        """Get the list of all users in InfluxDB.

        :returns: all users in InfluxDB
        :rtype: list of dictionaries

        :Example:

        ::

            >> users = client.get_list_users()
            >> users
            [{u'admin': True, u'user': u'user1'},
             {u'admin': False, u'user': u'user2'},
             {u'admin': False, u'user': u'user3'}]
        """
        ret = yield self.query("SHOW USERS")
        raise Return(list(ret.get_points()))

    @coroutine
    def create_user(self, username, password, admin=False):
        """Create a new user in InfluxDB

        :param username: the new username to create
        :type username: str
        :param password: the password for the new user
        :type password: str
        :param admin: whether the user should have cluster administration
            privileges or not
        :type admin: boolean
        """
        text = "CREATE USER {0} WITH PASSWORD {1}".format(
            quote_ident(username), quote_literal(password))
        if admin:
            text += ' WITH ALL PRIVILEGES'
        yield self.query(text)

    @coroutine
    def drop_user(self, username):
        """Drop a user from InfluxDB.

        :param username: the username to drop
        :type username: str
        """
        text = "DROP USER {0}".format(quote_ident(username))
        yield self.query(text)

    @coroutine
    def set_user_password(self, username, password):
        """Change the password of an existing user.

        :param username: the username who's password is being changed
        :type username: str
        :param password: the new password for the user
        :type password: str
        """
        text = "SET PASSWORD FOR {0} = {1}".format(
            quote_ident(username), quote_literal(password))
        yield self.query(text)

    @coroutine
    def delete_series(self, database=None, measurement=None, tags=None):
        """Delete series from a database. Series can be filtered by
        measurement and tags.

        :param database: the database from which the series should be
            deleted, defaults to client's current database
        :type database: str
        :param measurement: Delete all series from a measurement
        :type id: str
        :param tags: Delete all series that match given tags
        :type id: dict
        """
        database = database or self._database
        query_str = 'DROP SERIES'
        if measurement:
            query_str += ' FROM {0}'.format(quote_ident(measurement))

        if tags:
            tag_eq_list = ["{0}={1}".format(quote_ident(k), quote_literal(v))
                           for k, v in tags.items()]
            query_str += ' WHERE ' + ' AND '.join(tag_eq_list)
        yield self.query(query_str, database=database)

    @coroutine
    def grant_admin_privileges(self, username):
        """Grant cluster administration privileges to a user.

        :param username: the username to grant privileges to
        :type username: str

        .. note:: Only a cluster administrator can create/drop databases
            and manage users.
        """
        text = "GRANT ALL PRIVILEGES TO {0}".format(quote_ident(username))
        yield self.query(text)

    @coroutine
    def revoke_admin_privileges(self, username):
        """Revoke cluster administration privileges from a user.

        :param username: the username to revoke privileges from
        :type username: str

        .. note:: Only a cluster administrator can create/ drop databases
            and manage users.
        """
        text = "REVOKE ALL PRIVILEGES FROM {0}".format(quote_ident(username))
        yield self.query(text)

    @coroutine
    def grant_privilege(self, privilege, database, username):
        """Grant a privilege on a database to a user.

        :param privilege: the privilege to grant, one of 'read', 'write'
            or 'all'. The string is case-insensitive
        :type privilege: str
        :param database: the database to grant the privilege on
        :type database: str
        :param username: the username to grant the privilege to
        :type username: str
        """
        text = "GRANT {0} ON {1} TO {2}".format(privilege,
                                                quote_ident(database),
                                                quote_ident(username))
        yield self.query(text)

    @coroutine
    def revoke_privilege(self, privilege, database, username):
        """Revoke a privilege on a database from a user.

        :param privilege: the privilege to revoke, one of 'read', 'write'
            or 'all'. The string is case-insensitive
        :type privilege: str
        :param database: the database to revoke the privilege on
        :type database: str
        :param username: the username to revoke the privilege from
        :type username: str
        """
        text = "REVOKE {0} ON {1} FROM {2}".format(privilege,
                                                   quote_ident(database),
                                                   quote_ident(username))
        yield self.query(text)

    @coroutine
    def get_list_privileges(self, username):
        """Get the list of all privileges granted to given user.

        :param username: the username to get privileges of
        :type username: str

        :returns: all privileges granted to given user
        :rtype: list of dictionaries

        :Example:

        ::

            >> privileges = client.get_list_privileges('user1')
            >> privileges
            [{u'privilege': u'WRITE', u'database': u'db1'},
             {u'privilege': u'ALL PRIVILEGES', u'database': u'db2'},
             {u'privilege': u'NO PRIVILEGES', u'database': u'db3'}]
        """
        text = "SHOW GRANTS FOR {0}".format(quote_ident(username))
        ret = yield self.query(text)
        raise Return(list(ret.get_points()))
