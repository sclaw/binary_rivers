import networkx as nx
import network_cards as nc
import os
import sqlite3
import pandas as pd

# Load network
in_path = os.path.join(os.getcwd(), 'data', 'graph.db')
con = sqlite3.connect(in_path)
cur = con.cursor()
G = nx.DiGraph()

# Load data
edge_df = pd.read_sql_query("SELECT HYRIV_ID, NEXT_DOWN, LENGTH_KM, UPLAND_SKM, ORD_STRA FROM edges", con)
node_df = pd.read_sql_query("SELECT HYRIV_ID, longitude, latitude, basin FROM nodes", con)
con.close()

# Make graph
edges = edge_df[['HYRIV_ID', 'NEXT_DOWN']].values.tolist()
G.add_edges_from(edges)
edge_attrs = edge_df.set_index(['HYRIV_ID', 'NEXT_DOWN']).to_dict(orient='index')
nx.set_edge_attributes(G, edge_attrs)
node_attrs = node_df.set_index('HYRIV_ID').to_dict(orient='index')
nx.set_node_attributes(G, node_attrs)

# Make network card
card = nc.NetworkCard(G)

card.update_overall("Name", "North American Fifth-Order Streams")
card.update_overall("Kind", "Directed graph")
card.update_overall("Nodes are", "River confluences")
card.update_overall("Links are", "River segments between confluences")
card.update_overall("Links weights are", "One of the following: length (km), drainage area (sq.km.), strahler order")
card.update_overall("Considerations", None)
card_meta = {
    "Node metadata": "hyriv_id, latitude, longitude, subbasin ID",
    "Link metadata": "length (km), drainage area (sq.km.), strahler order",
    "Date of creation": 2024,
    "Data generating process": "Data was extracted from the HyrdoRIVERS data layer, a global dataset of rivers derived from 15 arc-second digital elevation data.  Lehner, B., Grill G. (2013): Global river hydrography and network routing: baseline data and new approaches to study the world’s large river systems. Hydrological Processes, 27(15): 2171–2186. Data is available at www.hydrosheds.org.",
    "Ethics": None,
    "Funding": None,
    "Citation": None,
    "Access": 'https://www.hydroshare.org/resource/6cf2c36bccb94055bd5264b847df3af1/'
}
card.update_metainfo(card_meta)
print(card)
card.to_latex(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'network_card.tex'))
card.to_frame().to_csv(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'network_card.csv'))