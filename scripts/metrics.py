import geopandas as gpd
import numpy as np
import queue


class Segment:

    def __init__(self, geom):
        self.geom = geom
        self.length = geom.length

        tmp_coords = []
        if geom.geom_type == 'MultiLineString':
            for line in geom.geoms:
                tmp_coords.extend(line.coords)
        else:
            tmp_coords = geom.coords
        self.coords = tmp_coords
        self.first = self.coords[0]
        self.last = self.coords[-1]

        dy = (self.last[1] - self.first[1])
        dx = (self.last[0] - self.first[0])
        tmp_slope = dy / dx if dx != 0 else 999999
    
        tmp_intercept = self.first[1] - (tmp_slope * self.first[0])
        self.d = ((self.last[0] - self.first[0]) ** 2 + (self.last[1] - self.first[1]) ** 2) ** 0.5

        if dx == 0:
            if dy > 0:
                self.orientation = 90
            else:
                self.orientation = -90
        else:
            self.orientation = (np.arctan2(np.array([dy]), np.array([dx])) / np.pi) * 180

        tmp_dist = 0
        for coord in self.coords:
            tmp_dist = max(tmp_dist, abs(tmp_slope * coord[0] - coord[1] + tmp_intercept) / (tmp_slope ** 2 + 1) ** 0.5)
        self.a = tmp_dist

        self.arc_l = None


    def curvature(self):
        return self.a / self.d
    

    def meander(self):
        if self.a == 0:
            return 0
        h = self.d / 2
        r = ((h ** 2) + (self.a ** 2)) / (2 * self.a)
        if abs(h - r) < 0.0001:
            alpha = np.pi / 2  # just kinda estimating by looking at the asymptote of arcsin on wolframalpha
        else:
            alpha = np.arcsin(h / r)
        
        self.arc_l = r * alpha
        return (self.length - self.arc_l) / self.arc_l
    

class Network:

    def __init__(self, gdf, from_field='HYRIV_ID', to_field='NEXT_DOWN', order_field='UPLAND_SKM', root=None):
        self.gdf = gdf
        self.gdf = self.gdf.set_index(from_field)
        self.da = gdf[order_field].max()
        self.from_field = from_field
        self.to_field = to_field

        if root is None:
            self.root = self.find_root()
        else:
            self.root = root

        self.edge_dict = dict()
        u = self.gdf.index.values
        v = self.gdf[to_field].values
        priority = {tmp_u: p for tmp_u, p in zip(u, self.gdf[order_field].values)}

        edge_dict = dict()
        for i in range(len(u)):
            if v[i] in edge_dict:
                if priority[u[i]] > priority[edge_dict[v[i]][0]]:
                    edge_dict[v[i]].insert(0, u[i])
                else:
                    edge_dict[v[i]].append(u[i])
            else:
                edge_dict[v[i]] = [u[i]]
        self.edge_dict = edge_dict

        self.gdf.loc[:, ['length', 'curvature', 'meander', 'orientation', 'depth', 'leaves', 'balance_factor', 'cum_depth', 'ave_depth', 'tja']] = np.nan
        self.calc_edge_metrics()

        self.post_order_traversal()
        self.metrics = self.calc_network_metrics()

    def find_root(self):
        root = self.gdf[self.gdf[self.to_field].isin(self.gdf.index) == False][self.to_field].unique()
        if len(root) > 1:
            raise ValueError('Multiple roots found')
        return root[0]

    def calc_edge_metrics(self):
        print('Calculating Edge Metrics...')
        for i in self.gdf.index:
            tmp_e = Segment(self.gdf.loc[i, 'geometry'])
            self.gdf.loc[i, 'length'] = tmp_e.length
            self.gdf.loc[i, 'curvature'] = tmp_e.curvature()
            self.gdf.loc[i, 'meander'] = tmp_e.meander()
            self.gdf.loc[i, 'orientation'] = tmp_e.orientation

    def calc_network_metrics(self):
        print('Calculating Network Metrics...')
        out_dict = dict()

        out_dict['ave_length'] = self.gdf['length'].mean()
        out_dict['med_length'] = self.gdf['length'].median()
        out_dict['std_length'] = self.gdf['length'].std()
        out_dict['ave_curvature'] = self.gdf['curvature'].mean()
        out_dict['med_curvature'] = self.gdf['curvature'].median()
        out_dict['std_curvature'] = self.gdf['curvature'].std()
        out_dict['ave_meander'] = self.gdf['meander'].mean()
        out_dict['med_meander'] = self.gdf['meander'].median()
        out_dict['std_meander'] = self.gdf['meander'].std()
        out_dict['ave_orientation'] = self.gdf['orientation'].mean()
        out_dict['med_orientation'] = self.gdf['orientation'].median()
        out_dict['std_orientation'] = self.gdf['orientation'].std()

        tjas = self.gdf['tja'].dropna()
        out_dict['ave_tja'] = tjas.mean()
        out_dict['med_tja'] = tjas.median()
        out_dict['std_tja'] = tjas.std()

        out_dict['med_depth'] = self.gdf['depth'].median()
        out_dict['std_depth'] = self.gdf['depth'].std()
        out_dict['ave_balance'] = self.gdf['balance_factor'].mean()
        out_dict['med_balance'] = self.gdf['balance_factor'].median()
        out_dict['std_balance'] = self.gdf['balance_factor'].std()

        out_dict['leaves'] = self.gdf.loc[self.root, 'leaves']
        out_dict['ave_depth'] = self.gdf.loc[self.root, 'ave_depth']
        out_dict['height'] = self.gdf['depth'].max()
        out_dict['compactness'] = out_dict['height'] / out_dict['leaves']

        out_dict['density'] = self.gdf['length'].sum() / self.da
        out_dict['texture'] = len(self.gdf) / self.da

        bifurcation = self.bifurcation_ratios()
        for i in bifurcation:
            out_dict[i] = bifurcation[i]

        return out_dict

    def bifurcation_ratios(self):
        present_orders = sorted(self.gdf['ORD_STRA'].dropna().unique())
        out_dict = dict()
        for i in range(len(present_orders) - 1):
            i += 2
            out_dict[f'bifurcation_{i}'] = np.sum(self.gdf['ORD_STRA'] == i - 1) / np.sum(self.gdf['ORD_STRA'] == i)
        out_dict['bifurcation_mean'] = np.sum(self.gdf['ORD_STRA'] == 1) ** (1 / (max(present_orders) - 1))
        return out_dict

    def calc_junction_angles(self):
        init_list = self.gdf[[self.to_field]]
        init_list = init_list.merge(init_list, left_index=True, right_on=self.to_field, how='left')
        init_list = init_list[init_list[self.to_field + '_y'].isna()][self.to_field + '_x'].unique()

        q = queue.Queue()
        [q.put(i) for i in init_list]
        evaluated = dict()
        all_edges = self.gdf[self.from_field].to_list()
        while not q.empty():
            cur_node = q.get()
            if not cur_node in all_edges:
                continue
            
            tribs = self.gdf[self.gdf[self.to_field] == cur_node][self.from_field].index
            if len(tribs) != 2:
                continue
            tja = abs(self.gdf.loc[tribs[0], 'orientation'] - self.gdf.loc[tribs[1], 'orientation'])
            if tja > 180:
                tja = 360 - tja
            evaluated[cur_node] = tja

            next_down = self.edges[self.edges[self.from_field] == cur_node][self.to_field].item()
            if not next_down in evaluated:
                q.put(next_down)
        return evaluated
    
    def _process_node(self, node):
        if node not in self.edge_dict:
            self.gdf.loc[node, 'depth'] = 0
            self.gdf.loc[node, 'leaves'] = 1
            self.gdf.loc[node, 'balance_factor'] = 0
            self.gdf.loc[node, 'cum_depth'] = 0
            self.gdf.loc[node, 'ave_depth'] = 0
            self.gdf.loc[node, 'tja'] = np.nan
        else:
            children = self.edge_dict[node]
            sub_df = self.gdf.loc[children]
            depths = sub_df['depth'].values
            self.gdf.loc[node, 'depth'] = depths.max() + 1
            leaves = sub_df['leaves'].sum()
            self.gdf.loc[node, 'leaves'] = leaves
            cum_depth = sub_df['cum_depth'].sum() + leaves
            self.gdf.loc[node, 'cum_depth'] = cum_depth
            self.gdf.loc[node, 'ave_depth'] = cum_depth / leaves
            self.gdf.loc[node, 'balance_factor'] = depths[0] - depths[1]
            orientations = sub_df['orientation'].values
            tja = abs(orientations[0] - orientations[1])
            if tja > 180:
                tja = 360 - tja
            self.gdf.loc[node, 'tja'] = tja
            
    def post_order_traversal(self):
        print('Traversing Network...')
        
        q = [self.root]
        visited = []
        while q:
            cur_node = q[-1]
            if cur_node not in self.edge_dict or all([child in visited for child in self.edge_dict[cur_node]]):
                q.pop()
                self._process_node(cur_node)
                visited.append(cur_node)
            else:
                for child in self.edge_dict[cur_node]:
                    if child not in visited:
                        q.append(child)
        return visited





