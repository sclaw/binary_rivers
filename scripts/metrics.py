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
        alpha = np.arcsin(h / r)
        self.arc_l = r * alpha
        return (self.length - self.arc_l) / self.arc_l
    

class Network:

    def __init__(self, gdf, da, from_field='HYRIV_ID', to_field='NEXT_DOWN'):
        self.gdf = gdf
        self.da = da
        self.from_field = from_field
        self.to_field = to_field
        self.edges = self.gdf[[from_field, to_field]]

        self.gdf.loc[:, ['length', 'curvature', 'meander', 'orientation']] = np.nan
        self.calc_edge_metrics()

        self.metrics = self.calc_network_metrics()

    def calc_edge_metrics(self):
        for i in range(len(self.gdf)):
            i = self.gdf.index[i]
            tmp_e = Segment(self.gdf.loc[i, 'geometry'])
            self.gdf.loc[i, 'length'] = tmp_e.length
            self.gdf.loc[i, 'curvature'] = tmp_e.curvature()
            self.gdf.loc[i, 'meander'] = tmp_e.meander()
            self.gdf.loc[i, 'orientation'] = tmp_e.orientation

    def calc_network_metrics(self):
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

        tjas = self.calc_junction_angles()
        tjas = np.array([i for i in tjas.values()])
        out_dict['ave_tja'] = tjas.mean()
        out_dict['med_tja'] = np.median(tjas)
        out_dict['std_tja'] = tjas.std()

        out_dict['density'] = self.gdf['length'].sum() / self.da
        out_dict['texture'] = len(self.gdf) / self.da

        bifurcation = self.bifurcation_ratios()
        for i in bifurcation:
            out_dict[i] = bifurcation[i]

        return out_dict

    def bifurcation_ratios(self):
        present_orders = sorted(self.gdf['ORD_STRA'].unique())
        out_dict = dict()
        for i in range(len(present_orders) - 1):
            i += 2
            out_dict[f'bifurcation_{i}'] = np.sum(self.gdf['ORD_STRA'] == i - 1) / np.sum(self.gdf['ORD_STRA'] == i)
        out_dict['mean'] = np.sum(self.gdf['ORD_STRA'] == 1) ** (1 / (max(present_orders) - 1))
        return out_dict

    def calc_junction_angles(self):
        init_list = self.edges.merge(self.edges, left_on=self.from_field, right_on=self.to_field, how='left')
        init_list = init_list[init_list[self.from_field + '_y'].isna()][self.to_field + '_x'].unique()

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




