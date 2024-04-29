from pathlib import Path
import sys
import os
base_dir = str(Path(__file__).parents[1])
sys.path.append(base_dir)
from binary_rivers.extract_graph import *

# Define paths to and from data
in_path = os.path.join(base_dir, 'data', 'HydroRIVERS_v10_na.gdb')  # Downloaded from https://www.hydrosheds.org/products/hydrorivers
out_path =  os.path.join(base_dir, 'data', 'graph.db')

# Process data
extract_graph(in_path, out_path)
label_basins(out_path, 5)
prune_graph(out_path)
enforcce_binary(out_path)
