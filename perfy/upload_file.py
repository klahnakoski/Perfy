# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from datetime import datetime, timedelta
from perfy.util.cnv import CNV
from perfy.util.env.logs import Log
from perfy.util.env import startup
from perfy.util.env.files import File
from perfy.util.env.elasticsearch import ElasticSearch
from perfy.util.queries import Q


far_back = datetime.utcnow() - timedelta(weeks=52)
BATCH_SIZE = 100000


# USE THE source TO GET THE INDEX SCHEMA
def get_or_create_index(destination_settings):
    #CHECK IF INDEX, OR ALIAS, EXISTS
    es = ElasticSearch(destination_settings)
    aliases = es.get_aliases()

    indexes = [a for a in aliases if a.alias == destination_settings.index or a.index == destination_settings.index]
    if not indexes:
        schema = CNV.JSON2object(File(destination_settings.schema_filename).read())
        return ElasticSearch.create_index(destination_settings, schema)
    elif len(indexes) > 1:
        Log.error("do not know how to replicate to more than one index")
    elif indexes[0].alias != None:
        destination_settings.alias = indexes[0].alias
        destination_settings.index = indexes[0].index

    return ElasticSearch(destination_settings)


def main(settings):
    # SYNCH WITH source ES INDEX

    destination = get_or_create_index(settings.destination)

    source = File("C:/Users/klahnakoski/Downloads/records.json").read()
    lines = [CNV.JSON2object(l) for l in source.split("\n") if l.strip()]
    records = [{"id": lines[i].index._id, "value": lines[i + 1]} for i in range(0, len(lines), 2)]
    for g, r in Q.groupby(records, size=1000):
        destination.extend(r)
        Log.note("Added {{num}}", {"num": len(r)})

    Log.note("Done")


def start():
    try:
        settings = startup.read_settings()
        Log.start(settings.debug)
        main(settings)
    except Exception, e:
        Log.error("Problems exist", e)
    finally:
        Log.stop()


if __name__ == "__main__":
    start()
