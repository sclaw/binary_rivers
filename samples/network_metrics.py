from pathlib import Path
import sys
import os
base_dir = str(Path(__file__).parents[1])
sys.path.append(base_dir)
import geopandas as gpd
from binary_rivers.metrics import Network

# Load geospatial data for network
in_path = os.path.join(base_dir, 'data', 'connecticut.gpkg')
gdf = gpd.read_file(in_path)

# Create network object
network = Network(gdf)
[print(d) for d in network.metrics.items()]