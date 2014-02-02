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
from perfy.util.timer import Timer
from perfy.util.cnv import CNV
from perfy.util.env.logs import Log
from perfy.util.queries import Q
from perfy.util.env import startup
from perfy.util.env.files import File
from perfy.util.collections.multiset import Multiset
from perfy.util.env.elasticsearch import ElasticSearch


far_back = datetime.utcnow() - timedelta(weeks=52)
BATCH_SIZE = 100000


def transform(record):
    # record.info.started = CNV.datetime2milli(CNV.string2datetime(record.info.started, "%Y-%m-%d  %H:%M:%S.%f"))
    # record.info.started *= 1000
    return record


def get_last_updated(es):
    try:
        results = es.search({
            "query": {"filtered": {
                "query": {"match_all": {}},
                "filter": {
                    "range": {
                    "modified_ts": {"gte": CNV.datetime2milli(far_back)}}}
            }},
            "from": 0,
            "size": 0,
            "sort": [],
            "facets": {"0": {"statistical": {"field": "modified_ts"}}}
        })

        if results.facets["0"].count == 0:
            return datetime.min
        return CNV.milli2datetime(results.facets["0"].max)
    except Exception, e:
        Log.error("Can not get_last_updated from {{host}}/{{index}}",{
            "host": es.settings.host,
            "index": es.settings.index
        }, e)



# USE THE source TO GET THE INDEX SCHEMA
def get_or_create_index(destination_settings, source):
    #CHECK IF INDEX, OR ALIAS, EXISTS
    es = ElasticSearch(destination_settings)
    aliases = es.get_aliases()

    indexes = [a for a in aliases if a.alias == destination_settings.index or a.index == destination_settings.index]
    if not indexes:
        #CREATE INDEX
        if destination_settings.schema_filename:
            schema = CNV.JSON2object(File(destination_settings.schema_filename).read())
        else:
            schema = source.get_schema()

        assert schema.settings
        assert schema.mappings
        ElasticSearch.create_index(destination_settings, schema)
    elif len(indexes) > 1:
        Log.error("do not know how to replicate to more than one index")
    elif indexes[0].alias != None:
        destination_settings.alias = indexes[0].alias
        destination_settings.index = indexes[0].index

    return ElasticSearch(destination_settings)


def get_pending(es, id_field_name, esfilter):
    result = es.search({
        "query": {"filtered": {
            "query": {"match_all": {}},
            "filter": esfilter
        }},
        "from": 0,
        "size": 0,
        "sort": [],
        "facets": {"default": {"terms": {"field": id_field_name, "size": 200000}}}
    })

    if len(result.facets.default.terms) >= 200000:
        Log.error("Can not handle more than 200K bugs changed")

    pending = Multiset(
        result.facets.default.terms,
        key_field="term",
        count_field="count"
    )
    Log.note("Source has {{num}} records for updating", {
        "num": len(pending)
    })
    return pending


def replicate(source, destination, pending, id_field_name, esfilter):
    """
    COPY source RECORDS TO destination
    """
    for g, ids in Q.groupby(pending, max_size=BATCH_SIZE):
        with Timer("Replicate {{num}} records...", {"num": len(ids)}):
            data = source.search({
                "query": {"filtered": {
                    "query": {"match_all": {}},
                    "filter": {"and": [
                        {"terms": {id_field_name: set(ids)}},
                        esfilter
                    ]}
                }},
                "from": 0,
                "size": 200000,
                "sort": []
            })

            d2 = map(
                lambda(x): {"id": x.id, "value": x},
                (transform(x._source) for x in data.hits.hits)
            )
            destination.add(d2)


def main(settings):
    # SYNCH WITH source ES INDEX
    source = ElasticSearch(settings.source)
    destination = get_or_create_index(settings["destination"], source)

    id_field_name = "info.started"
    esfilter = {"script": {"script": "true"}}

    pending = get_pending(source, id_field_name, esfilter)
    replicate(source, destination, pending, id_field_name, esfilter)
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
