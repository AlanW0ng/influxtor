# influxtor
A asynchronous influxdb client with tornado, modified from[https://github.com/influxdata/influxdb-python](https://github.com/influxdata/influxdb-python)
# Example
```python
# coding: utf-8

import tornado.ioloop
import tornado.web
from tornado.gen import coroutine
from influxtor import InfluxDBClient

INFLUXDB_HOST = "127.0.0.1"
INFLUXDB_PORT = 8086
INFLUXDB_USER = None
INFLUXDB_PASSWORD = None
INFLUDB_DATABASE = "example"
# database has been created before
client = InfluxDBClient(INFLUXDB_HOST, INFLUXDB_PORT, INFLUXDB_USER, INFLUXDB_PASSWORD, INFLUDB_DATABASE)



class QueryHandler(tornado.web.RequestHandler):

    @coroutine
    def get(self):
        minutes_ago = self.get_argument("m", None)

        try:
            minutes_ago = int(minutes_ago)
        except:
            self.write("Wrong \"m\"")
            return
        remote_ip = self.request.remote_ip
        query_str = "SELECT value FROM example_data WHERE remote_ip = '%s' AND time > now() - %dm" % (remote_ip, minutes_ago)
        res = yield client.query(query_str)
        self.write("{0}".format(res))


class WriteHandler(tornado.web.RequestHandler):

    @coroutine
    def get(self):
        self.write(
            '<form method="post">'
            '<p>value: <input type="text" name="v"></p>'
            '<input type="submit">'
            '</form>'
        )


    @coroutine
    def post(self):
        v = self.get_argument("v", None)
        try:
            v = int(v)
        except:
            self.write("Wrong Value")
            return
        remote_ip = self.request.remote_ip
        res = yield client.write_points([{
            "measurement": "example_data",
            "tags": {
                "remote_ip": remote_ip
            },
            "fields": {
                "value": v
            }
        }])
        self.write("{0}".format(res))


def make_app():
    return tornado.web.Application([
        (r"/query", QueryHandler),
        (r"/write", WriteHandler)
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
```
