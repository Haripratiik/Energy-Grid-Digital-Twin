export interface BusGeo {
  id: number;
  x: number;
  y: number;
  district: string;
}

export interface DistrictRegion {
  name: string;
  color: string;
  points: [number, number][];
}

export interface CityMapPreset {
  id: string;
  name: string;
  description: string;
  buses: BusGeo[];
  districts: DistrictRegion[];
  riverPath: string;
}
