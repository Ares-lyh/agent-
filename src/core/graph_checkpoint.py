"""SQLite LangGraph checkpointer; checkpoint.json remains the business authority.

The serializer is LangGraph's typed serializer, never pickle. SQLite transactions
persist graph positions and pending writes across application restarts.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP

class SQLiteGraphSaver(BaseCheckpointSaver):
    def __init__(self, path):
        super().__init__()
        self.path = str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS graph_checkpoints (
                  thread_id TEXT, namespace TEXT, checkpoint_id TEXT, parent_id TEXT,
                  checkpoint_type TEXT, checkpoint_blob BLOB, metadata_type TEXT, metadata_blob BLOB,
                  PRIMARY KEY(thread_id,namespace,checkpoint_id));
                CREATE TABLE IF NOT EXISTS graph_writes (
                  thread_id TEXT, namespace TEXT, checkpoint_id TEXT, task_id TEXT, write_index INTEGER,
                  channel TEXT, value_type TEXT, value_blob BLOB,
                  PRIMARY KEY(thread_id,namespace,checkpoint_id,task_id,write_index));
            """)

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_tuple(self, config):
        options=config["configurable"]
        thread=options["thread_id"]; namespace=options.get("checkpoint_ns","")
        checkpoint_id=options.get("checkpoint_id")
        with self.connection() as db:
            if checkpoint_id:
                row=db.execute("SELECT checkpoint_id,parent_id,checkpoint_type,checkpoint_blob,metadata_type,metadata_blob FROM graph_checkpoints WHERE thread_id=? AND namespace=? AND checkpoint_id=?",
                               (thread,namespace,checkpoint_id)).fetchone()
            else:
                row=db.execute("SELECT checkpoint_id,parent_id,checkpoint_type,checkpoint_blob,metadata_type,metadata_blob FROM graph_checkpoints WHERE thread_id=? AND namespace=? ORDER BY checkpoint_id DESC LIMIT 1",
                               (thread,namespace)).fetchone()
            if row is None:
                return None
            writes=db.execute("SELECT task_id,channel,value_type,value_blob FROM graph_writes WHERE thread_id=? AND namespace=? AND checkpoint_id=? ORDER BY task_id,write_index",
                              (thread,namespace,row[0])).fetchall()
        return CheckpointTuple(
            config={"configurable":{"thread_id":thread,"checkpoint_ns":namespace,"checkpoint_id":row[0]}},
            checkpoint=self.serde.loads_typed((row[2],row[3])),
            metadata=self.serde.loads_typed((row[4],row[5])),
            parent_config={"configurable":{"thread_id":thread,"checkpoint_ns":namespace,"checkpoint_id":row[1]}} if row[1] else None,
            pending_writes=[(task,channel,self.serde.loads_typed((kind,value))) for task,channel,kind,value in writes])

    def put(self, config, checkpoint, metadata, new_versions):
        options=config["configurable"]; thread=options["thread_id"]; namespace=options.get("checkpoint_ns","")
        kind,payload=self.serde.dumps_typed(checkpoint)
        metadata_kind,metadata_payload=self.serde.dumps_typed(metadata)
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO graph_checkpoints VALUES(?,?,?,?,?,?,?,?)",
                (thread,namespace,checkpoint["id"],options.get("checkpoint_id"),kind,payload,metadata_kind,metadata_payload))
        return {"configurable":{"thread_id":thread,"checkpoint_ns":namespace,"checkpoint_id":checkpoint["id"]}}

    def put_writes(self, config, writes, task_id, task_path=""):
        options=config["configurable"]
        with self.connection() as db:
            for index,(channel,value) in enumerate(writes):
                index=WRITES_IDX_MAP.get(channel,index)
                kind,payload=self.serde.dumps_typed(value)
                mode="REPLACE" if index<0 else "IGNORE"
                db.execute("INSERT OR "+mode+" INTO graph_writes VALUES(?,?,?,?,?,?,?,?)",
                    (options["thread_id"],options.get("checkpoint_ns",""),options["checkpoint_id"],
                     task_id,index,channel,kind,payload))

    def list(self, config, *, filter=None, before=None, limit=None):
        if config is None:
            return
        options=config["configurable"]
        with self.connection() as db:
            rows=db.execute("SELECT checkpoint_id FROM graph_checkpoints WHERE thread_id=? AND namespace=? ORDER BY checkpoint_id DESC",
                            (options["thread_id"],options.get("checkpoint_ns",""))).fetchall()
        count=0
        for (checkpoint_id,) in rows:
            if before and checkpoint_id>=before["configurable"]["checkpoint_id"]:
                continue
            item=self.get_tuple({"configurable":{**options,"checkpoint_id":checkpoint_id}})
            if filter and any(item.metadata.get(key)!=value for key,value in filter.items()):
                continue
            if limit is not None and count>=limit:
                break
            yield item
            count+=1

    def delete_thread(self, thread_id):
        with self.connection() as db:
            db.execute("DELETE FROM graph_writes WHERE thread_id=?",(thread_id,))
            db.execute("DELETE FROM graph_checkpoints WHERE thread_id=?",(thread_id,))
