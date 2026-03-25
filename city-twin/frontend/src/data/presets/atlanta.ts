import type { CityMapPreset } from "./types";

/**
 * Atlanta Metro area — illustrative layout, not official GIS.
 *
 * Geography metaphor (900x700 SVG):
 *   North: Buckhead / Perimeter / Roswell
 *   Center: Midtown / Downtown (dense core ~y 280-380)
 *   West: Chattahoochee corridor, industrial
 *   East: Decatur, Stone Mountain suburbs
 *   South: Hartsfield-Jackson Airport, Southside
 *   Far east: Plant Vogtle proxy (nuclear)
 *   Northwest: hydro (Buford Dam proxy)
 */

const atlanta: CityMapPreset = {
  id: "atlanta",
  name: "Atlanta Metro",
  description: "Atlanta-inspired 80-bus layout: Plant Vogtle nuclear, Buford Dam hydro, Midtown/Downtown core, Hartsfield-Jackson corridor, Chattahoochee river.",
  buses: [
    // === 400 kV (1-5) — major generation at metro edges ===
    { id: 1, x: 810, y: 90, district: "Plant Vogtle (Nuclear)" },
    { id: 2, x: 320, y: 45, district: "Buford Dam (Hydro)" },
    { id: 3, x: 160, y: 340, district: "Chattahoochee Gas Plant" },
    { id: 4, x: 780, y: 260, district: "NE Georgia Wind Farm" },
    { id: 5, x: 450, y: 650, district: "Spalding Solar Farm" },

    // === 132 kV (6-25) — substations ===
    { id: 6, x: 300, y: 150, district: "Sandy Springs Sub" },
    { id: 7, x: 430, y: 130, district: "Dunwoody Sub" },
    { id: 8, x: 340, y: 260, district: "West Midtown Gas" },
    { id: 9, x: 200, y: 280, district: "Smyrna Industrial" },
    { id: 10, x: 380, y: 390, district: "East Point Gas" },
    { id: 11, x: 180, y: 400, district: "Austell Manufacturing" },
    { id: 12, x: 420, y: 80, district: "Cumming Hydro" },
    { id: 13, x: 120, y: 510, district: "Newnan Logistics" },
    { id: 14, x: 300, y: 450, district: "College Park Rail" },
    { id: 15, x: 720, y: 200, district: "Athens Wind 2" },
    { id: 16, x: 560, y: 170, district: "Doraville Data Center" },
    { id: 17, x: 640, y: 400, district: "Hartsfield-Jackson" },
    { id: 18, x: 580, y: 560, district: "Griffin Solar 2" },
    { id: 19, x: 160, y: 550, district: "Carrollton Chemical" },
    { id: 20, x: 430, y: 490, district: "Union City Gas" },
    { id: 21, x: 540, y: 90, district: "Lawrenceville WTP" },
    { id: 22, x: 810, y: 330, district: "Augusta Wind 3" },
    { id: 23, x: 620, y: 290, district: "Emory / CDC" },
    { id: 24, x: 560, y: 350, district: "Grady Hospital" },
    { id: 25, x: 460, y: 150, district: "Perimeter North" },

    // === 33 kV (26-80) — distribution ===
    { id: 26, x: 280, y: 120, district: "Roswell" },
    { id: 27, x: 400, y: 100, district: "Alpharetta" },
    { id: 28, x: 350, y: 180, district: "Buckhead" },
    { id: 29, x: 440, y: 280, district: "Downtown Core" },
    { id: 30, x: 500, y: 260, district: "Old Fourth Ward" },
    { id: 31, x: 380, y: 290, district: "Vine City" },
    { id: 32, x: 220, y: 500, district: "Palmetto" },
    { id: 33, x: 360, y: 540, district: "Fayetteville" },
    { id: 34, x: 290, y: 520, district: "Fairburn" },
    { id: 35, x: 440, y: 330, district: "Grant Park" },
    { id: 36, x: 510, y: 310, district: "Reynoldstown" },
    { id: 37, x: 550, y: 260, district: "Decatur" },
    { id: 38, x: 300, y: 350, district: "West End" },
    { id: 39, x: 400, y: 340, district: "Mechanicsville" },
    { id: 40, x: 180, y: 360, district: "Mableton" },
    { id: 41, x: 250, y: 400, district: "Lithia Springs" },
    { id: 42, x: 150, y: 450, district: "Douglasville" },
    { id: 43, x: 330, y: 460, district: "Red Oak" },
    { id: 44, x: 270, y: 480, district: "South Fulton" },
    { id: 45, x: 390, y: 500, district: "Riverdale" },
    { id: 46, x: 100, y: 580, district: "Villa Rica" },
    { id: 47, x: 500, y: 380, district: "East Atlanta" },
    { id: 48, x: 530, y: 340, district: "Ormewood Park" },
    { id: 49, x: 460, y: 420, district: "Hapeville" },
    { id: 50, x: 530, y: 430, district: "Conley" },
    { id: 51, x: 480, y: 350, district: "Capitol District" },
    { id: 52, x: 360, y: 410, district: "MARTA Hub Five Pts" },
    { id: 53, x: 410, y: 440, district: "MARTA Hub Airport" },
    { id: 54, x: 590, y: 400, district: "Emory Hospital" },
    { id: 55, x: 630, y: 330, district: "Georgia Tech" },
    { id: 56, x: 310, y: 560, district: "Peachtree City" },
    { id: 57, x: 430, y: 560, district: "Jonesboro" },
    { id: 58, x: 240, y: 550, district: "Tyrone" },
    { id: 59, x: 500, y: 520, district: "Stockbridge" },
    { id: 60, x: 550, y: 480, district: "McDonough" },
    { id: 61, x: 650, y: 450, district: "Covington" },
    { id: 62, x: 670, y: 510, district: "Conyers" },
    { id: 63, x: 710, y: 460, district: "Lithonia" },
    { id: 64, x: 610, y: 460, district: "Panola Ind." },
    { id: 65, x: 570, y: 150, district: "Tucker" },
    { id: 66, x: 490, y: 120, district: "Norcross" },
    { id: 67, x: 530, y: 170, district: "Chamblee" },
    { id: 68, x: 650, y: 210, district: "Stone Mountain" },
    { id: 69, x: 710, y: 280, district: "Snellville" },
    { id: 70, x: 770, y: 400, district: "Monroe" },
    { id: 71, x: 370, y: 220, district: "Midtown Jct" },
    { id: 72, x: 370, y: 370, district: "Oakland City Jct" },
    { id: 73, x: 520, y: 460, district: "Forest Park Jct" },
    { id: 74, x: 690, y: 440, district: "Rockdale Jct" },
    { id: 75, x: 460, y: 540, district: "Hampton Jct" },
    { id: 76, x: 350, y: 600, district: "Senoia" },
    { id: 77, x: 410, y: 630, district: "Brooks" },
    { id: 78, x: 480, y: 600, district: "Locust Grove" },
    { id: 79, x: 540, y: 580, district: "Jackson" },
    { id: 80, x: 580, y: 630, district: "Barnesville" },
  ],
  districts: [
    { name: "Plant Vogtle", color: "#a78bfa", points: [[760,50],[860,50],[860,140],[760,140]] },
    { name: "Buford Dam", color: "#60a5fa", points: [[260,15],[400,15],[400,80],[260,80]] },
    { name: "Buckhead", color: "#fbbf24", points: [[290,140],[420,140],[420,210],[290,210]] },
    { name: "Midtown", color: "#f59e0b", points: [[340,220],[500,220],[500,310],[340,310]] },
    { name: "Downtown", color: "#f0a500", points: [[370,310],[520,310],[520,400],[370,400]] },
    { name: "Hartsfield-Jackson", color: "#545b6b", points: [[590,360],[700,360],[700,440],[590,440]] },
    { name: "Perimeter", color: "#34d399", points: [[430,100],[580,100],[580,180],[430,180]] },
    { name: "Southside", color: "#545b6b", points: [[300,440],[500,440],[500,570],[300,570]] },
    { name: "Chattahoochee Corridor", color: "#1e3a5f", points: [[140,230],[250,230],[250,420],[140,420]] },
    { name: "Solar Fields", color: "#fbbf24", points: [[400,600],[620,600],[620,670],[400,670]] },
    { name: "Decatur / Emory", color: "#60a5fa", points: [[530,240],[660,240],[660,340],[530,340]] },
  ],
  riverPath: "M 310,30 Q 290,60 270,110 Q 240,170 220,230 Q 200,280 185,340 Q 170,400 155,460 Q 140,510 120,560",
};

export default atlanta;
