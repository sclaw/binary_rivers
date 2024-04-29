from osgeo import ogr, osr
import sqlite3
from math import ceil
import time
import os


def insert_into_db(db_path, table_name, fields, dtypes, data, append=True):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Create a new table in the SQLite database, if necessary
    if not append:
        cur.execute('DROP TABLE IF EXISTS {}'.format(table_name))
        creation_command = "CREATE TABLE IF NOT EXISTS {} ({})".format(table_name, ', '.join([f'{f} {d}' for f, d in zip(fields, dtypes)]))
        cur.execute(creation_command)

    # Insert unique field values into the SQLite database
    insert_command = "INSERT INTO {} VALUES ({})".format(table_name, ', '.join(['?' for i in range(len(fields))]))
    cur.executemany(insert_command, data)

    # Commit changes and close connection
    conn.commit()
    conn.close()

def explore_db(db):
    # Get the number of layers in the geodatabase
    num_layers = db.GetLayerCount()

    # Iterate over layers and print their names
    for i in range(num_layers):
        layer = db.GetLayerByIndex(i)
        layer_name = layer.GetName()
        print(i, ":", layer_name)

    layer_name = 'NetworkNHDFlowline'
    layer = db.GetLayerByName(layer_name)
    layer_definition = layer.GetLayerDefn()
    num_fields = layer_definition.GetFieldCount()

    # Iterate over fields and print their names
    print("Fields in layer:", layer_name)
    for i in range(num_fields):
        field_def = layer_definition.GetFieldDefn(i)
        field_name = field_def.GetName()
        print(i, ":", field_name)

def extract_graph(in_path, out_path, batch_size=10000):
    """Extracts edge and node data from HydroRivers and saves it to a SQLite database."""
    
    # Load data
    driver = ogr.GetDriverByName("OpenFileGDB")
    geodatabase = driver.Open(in_path)
    layer_name = 'HydroRIVERS_v10_na'
    row_count = geodatabase.ExecuteSQL('SELECT COUNT(*) AS row_count FROM {}'.format(layer_name))
    row_count = [r.GetField('row_count') for r in row_count][0]
    batches = ceil(row_count / batch_size)

    # Set up query info
    edge_cols = ['HYRIV_ID', 'NEXT_DOWN', 'LENGTH_KM', 'UPLAND_SKM', 'ORD_STRA']
    edge_dtypes = ['INTEGER PRIMARY KEY', 'INTEGER', 'FLOAT', 'FLOAT', 'INTEGER']
    edge_base_query = "SELECT {} FROM {} LIMIT {} OFFSET {}"
    node_query_cols = ['shape', 'HYRIV_ID']
    node_cols = ['HYRIV_ID', 'longitude', 'latitude']
    node_dtypes = ['INTEGER PRIMARY KEY', 'FLOAT', 'FLOAT']
    node_base_query = "SELECT {} FROM {} LIMIT {} OFFSET {}"

    # Query and Export
    print('Extracting Edges')
    append = False
    false_start = 0
    for b in range(batches - false_start):
        t1 = time.perf_counter()
        b += false_start
        print(f'batch {b} / {batches}')
        if b > 0:
            append = True
        offset = b * batch_size

        # Get edges
        edge_query = edge_base_query.format(', '.join(edge_cols), layer_name, batch_size, offset)
        results = geodatabase.ExecuteSQL(edge_query)
        edge_values = [tuple(result.GetField(i) for i in range(len(edge_cols))) for result in results]
        geodatabase.ReleaseResultSet(results)

        # Get Nodes
        node_query = node_base_query.format(', '.join(node_query_cols), layer_name, batch_size, offset)
        results = geodatabase.ExecuteSQL(node_query)
        node_values = list()
        for f in results:
            x, y = f.geometry().GetGeometryRef(0).GetPoint(0)[0:2]  # this may get last point.  Not sure.  Need to debug, but good enough for now
            id = f.GetField('HYRIV_ID')
            node_values.append((id, x, y))
        geodatabase.ReleaseResultSet(results)

        # Log data to new db
        insert_into_db(out_path, 'edges', edge_cols, edge_dtypes, edge_values, append=append)
        insert_into_db(out_path, 'nodes', node_cols, node_dtypes, node_values, append=append)
        print(f'Finished in {round(time.perf_counter() - t1, 3)} seconds')

def label_basins(db_path, order_thresh):
    """ Selects root nodes at a certain order threshold and recursively labels all upstream nodes with the root node."""

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    root_query = sql_query = """
        SELECT t1.hyriv_id
        FROM edges t1
        JOIN edges t2 ON t1.next_down = t2.hyriv_id
        WHERE t1.ord_stra = ?
          AND t2.ord_stra > ?;
    """
    cur.execute(sql_query, (order_thresh, order_thresh))
    roots = [i[0] for i in cur.fetchall()]

    root_query = '''
    WITH RECURSIVE Upstream AS (
        -- Anchor member: select initial rows to start the recursion
        SELECT hyriv_id, next_down
        FROM edges
        WHERE next_down = {}
    
        UNION ALL
    
        -- Recursive member: select rows that lead to the current nodes
        SELECT c.hyriv_id, c.next_down
        FROM edges c
        JOIN Upstream u ON c.next_down = u.hyriv_id
    )
    -- Final query: hyriv_id all upstream connections leading to the root
    SELECT DISTINCT hyriv_id
    FROM Upstream;
    '''        
    counter = 0
    cur.execute('ALTER TABLE nodes DROP basin')
    cur.execute('ALTER TABLE nodes ADD basin INT DEFAULT -1')
    for root_node in roots:
        print(counter)
        tmp_query = root_query.format(root_node)
        res = cur.execute(tmp_query)
        reaches = res.fetchall()
        reaches = [i[0] for i in reaches]
        cur.execute('UPDATE nodes SET basin = {} WHERE hyriv_id IN ({})'.format(root_node, ", ".join("?" * len(reaches))), reaches)
        counter += 1
    con.commit()
    con.close()

def label_basins_tree_search(db_path, order_thresh):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    root_query = sql_query = """
        SELECT t1.hyriv_id
        FROM edges t1
        JOIN edges t2 ON t1.next_down = t2.hyriv_id
        WHERE t1.ord_stra = ?
          AND t2.ord_stra > ?;
    """
    cur.execute(sql_query, (order_thresh, order_thresh))
    roots = [i[0] for i in cur.fetchall()]

    counter = 0
    try:
        cur.execute('ALTER TABLE nodes ADD basin INT DEFAULT -1')
    except (NameError, sqlite3.OperationalError):
        cur.execute('ALTER TABLE nodes DROP basin')
        cur.execute('ALTER TABLE nodes ADD basin INT DEFAULT -1')

    for root_node in roots:
        print(counter)
        q = [root_node]
        reaches = []
        while q:
            cur_node = q[-1]
            q.pop()
            reaches.append(cur_node)
            cur.execute('SELECT hyriv_id FROM edges WHERE next_down = ?', (cur_node,))
            q.extend([i[0] for i in cur.fetchall()])
        cur.execute('UPDATE nodes SET basin = {} WHERE hyriv_id IN ({})'.format(root_node, ", ".join("?" * len(reaches))), reaches)
        counter += 1
    con.commit()
    con.close()

def prune_graph(db_path):
    """ Removes all nodes and edges that are not part of a basin. """

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    sql_query = "DELETE FROM edges WHERE hyriv_id IN (SELECT hyriv_id FROM nodes WHERE basin = -1)"
    cur.execute(sql_query)
    sql_query = "DELETE FROM nodes WHERE basin = -1"
    cur.execute(sql_query)
    con.commit()
    con.close()

def enforcce_binary(db_path):
    """ Ensures that all nodes have at most two children.  Inserts artificial edges and nodes to enforce this. """
    
    # SQL queries
    get_tribs = 'SELECT * FROM edges WHERE next_down = ?'
    bad_reach_query = 'SELECT t1.* FROM edges t1 JOIN (SELECT next_down, COUNT(*) AS count_next_down FROM edges GROUP BY next_down) t2 ON t1.hyriv_id = t2.next_down WHERE t2.count_next_down > 2;'
    max_id_query = 'SELECT max(hyriv_id) AS max FROM nodes'
    delete_query = 'DELETE FROM edges WHERE hyriv_id in ({})'

    # Load DB
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # get max_id
    cur.execute(max_id_query)
    max_id = cur.fetchall()[0][0]

    # Process
    cur.execute(bad_reach_query)
    bad_reaches = cur.fetchall()
    while len(bad_reaches) != 0:
        print(f'Found {len(bad_reaches)} triple confluences')
        counter = 0
        for r in bad_reaches:
            if counter % 100 == 0:
                print(f' - Processed {counter}')
            counter += 1
            cur.execute('SELECT * FROM nodes WHERE hyriv_id = ?', (r[0],))
            r_node = cur.fetchall()[0]
            cur.execute(get_tribs, (r[0],))
            tribs = cur.fetchall()
            das = [i[3] for i in tribs]
            tribs = [list(t) for d, t in sorted(zip(das, tribs))]

            add_reaches = len(tribs) - 2
            new_edges = list()
            new_nodes = list()
            parent = r[0]
            for i in range(add_reaches):
                max_id += 1
                new_edges.append([max_id, parent, 0, r[3] - tribs[i][3], r[4]])  # This r[4] could be improved in the future
                parent = max_id
                new_nodes.append([max_id, r_node[1], r_node[2], r_node[3]])
                tribs[i + 1][1] = max_id
            tribs[-1][1] = max_id

            combo_edges = [*tribs, *new_edges]

            tmp_delete_query = delete_query.format(", ".join("?" * len(combo_edges)))
            cur.execute(tmp_delete_query, [i[0] for i in combo_edges])
            cur.executemany('INSERT INTO edges VALUES ({})'.format(", ".join("?" * len(combo_edges[0]))), combo_edges)
            cur.executemany('INSERT INTO nodes VALUES ({})'.format(", ".join("?" * len(new_nodes[0]))), new_nodes)
            con.commit()
        cur.execute(bad_reach_query)
        bad_reaches = cur.fetchall()
    con.close()

if __name__ == '__main__':
    in_path = os.path.join(os.getcwd(), 'data', 'HydroRIVERS_v10_na.gdb')
    out_path =  os.path.join(os.getcwd(), 'data', 'graph_2.db')
    extract_graph(in_path, out_path)
    label_basins(out_path, 5)
    prune_graph(out_path)
    enforcce_binary(out_path)