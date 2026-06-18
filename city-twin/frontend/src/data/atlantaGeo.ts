/**
 * Real Atlanta-metro coordinates [lat, lng] for every bus, placed at the actual
 * neighbourhood / landmark its preset names. Distant bulk generation (Plant
 * Vogtle, Augusta/Athens/NE-GA wind) is pulled to the eastern edge of the metro
 * view so the map stays focused on the city while remaining directionally true.
 */
export const ATLANTA_BUS_LATLNG: Record<number, [number, number]> = {
  1: [33.50, -83.55],   // Plant Vogtle (nuclear) — east edge
  2: [34.16, -84.07],   // Buford Dam (hydro) — north
  3: [33.79, -84.50],   // Chattahoochee gas plant (NW, on the river)
  4: [34.20, -83.60],   // NE Georgia wind farm
  5: [33.26, -84.28],   // Spalding / Griffin solar
  6: [33.924, -84.379], // Sandy Springs
  7: [33.946, -84.334], // Dunwoody
  8: [33.787, -84.412], // West Midtown gas
  9: [33.884, -84.514], // Smyrna industrial
  10: [33.679, -84.439], // East Point gas
  11: [33.813, -84.634], // Austell manufacturing
  12: [34.207, -84.140], // Cumming hydro
  13: [33.381, -84.799], // Newnan logistics
  14: [33.653, -84.449], // College Park rail
  15: [34.00, -83.56],   // Athens wind
  16: [33.898, -84.282], // Doraville data center
  17: [33.640, -84.427], // Hartsfield-Jackson
  18: [33.247, -84.264], // Griffin solar 2
  19: [33.580, -84.95],  // Carrollton chemical (west edge)
  20: [33.587, -84.542], // Union City gas
  21: [33.956, -83.988], // Lawrenceville WTP
  22: [33.42, -83.55],   // Augusta wind — east edge
  23: [33.792, -84.323], // Emory / CDC
  24: [33.753, -84.380], // Grady Hospital
  25: [33.924, -84.341], // Perimeter North
  26: [34.023, -84.362], // Roswell
  27: [34.075, -84.294], // Alpharetta
  28: [33.838, -84.379], // Buckhead
  29: [33.755, -84.390], // Downtown core
  30: [33.764, -84.371], // Old Fourth Ward
  31: [33.756, -84.413], // Vine City
  32: [33.519, -84.669], // Palmetto
  33: [33.448, -84.455], // Fayetteville
  34: [33.567, -84.580], // Fairburn
  35: [33.737, -84.371], // Grant Park
  36: [33.751, -84.355], // Reynoldstown
  37: [33.775, -84.296], // Decatur
  38: [33.735, -84.418], // West End
  39: [33.740, -84.402], // Mechanicsville
  40: [33.819, -84.542], // Mableton
  41: [33.793, -84.661], // Lithia Springs
  42: [33.751, -84.748], // Douglasville
  43: [33.629, -84.510], // Red Oak
  44: [33.630, -84.530], // South Fulton
  45: [33.572, -84.413], // Riverdale
  46: [33.732, -84.918], // Villa Rica (west edge)
  47: [33.741, -84.341], // East Atlanta
  48: [33.736, -84.355], // Ormewood Park
  49: [33.660, -84.410], // Hapeville
  50: [33.645, -84.328], // Conley
  51: [33.749, -84.388], // Capitol District
  52: [33.754, -84.392], // MARTA Five Points
  53: [33.640, -84.446], // MARTA Airport
  54: [33.792, -84.323], // Emory Hospital
  55: [33.776, -84.398], // Georgia Tech
  56: [33.397, -84.596], // Peachtree City
  57: [33.521, -84.354], // Jonesboro
  58: [33.471, -84.597], // Tyrone
  59: [33.544, -84.234], // Stockbridge
  60: [33.447, -84.147], // McDonough
  61: [33.597, -83.860], // Covington
  62: [33.668, -84.018], // Conyers
  63: [33.712, -84.105], // Lithonia
  64: [33.690, -84.130], // Panola industrial
  65: [33.854, -84.217], // Tucker
  66: [33.941, -84.213], // Norcross
  67: [33.892, -84.299], // Chamblee
  68: [33.808, -84.170], // Stone Mountain
  69: [33.857, -84.020], // Snellville
  70: [33.795, -83.713], // Monroe
  71: [33.781, -84.383], // Midtown junction
  72: [33.722, -84.426], // Oakland City junction
  73: [33.622, -84.369], // Forest Park junction
  74: [33.660, -84.030], // Rockdale junction
  75: [33.386, -84.283], // Hampton junction
  76: [33.302, -84.554], // Senoia
  77: [33.288, -84.460], // Brooks
  78: [33.345, -84.109], // Locust Grove
  79: [33.295, -83.966], // Jackson
  80: [33.054, -84.156], // Barnesville (south edge)
};
