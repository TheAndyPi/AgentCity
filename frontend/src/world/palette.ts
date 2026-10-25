/** World colors for the dark cyberpunk city and its pastel daytime twin. */
export type WorldTheme = "dark" | "light";

export const neon = {
  cyan: "#00f0ff",
  magenta: "#ff0055",
  pink: "#ff4fc3",
  green: "#00ff66",
  yellow: "#ffe45c",
  violet: "#b98cff",
};

const palettes = {
  dark: {
    sky: "#0d0d11",
    base: "#08080c",
    land: "#15121f",
    landGrain: ["#2a2440", "#05050a"],
    grid: "#00f0ff",
    asphalt: "#1d1a29",
    asphaltGrain: ["#3a3550", "#07070b"],
    water: "#05303d",
    waterGlow: "#00c8e0",
    sidewalk: "#2e2946",
    curb: "#1fd8ea",
    markings: "#ff0055",
    unlit: "#2a2548",
    offline: "#3a3740",
    trimOffline: "#4a4752",
  },
  light: {
    sky: "#efe6fa",
    base: "#d9cdea",
    land: "#e6dcf3",
    landGrain: ["#ffffff", "#c9b9e2"],
    grid: "#8f6ce0",
    asphalt: "#c9bddd",
    asphaltGrain: ["#ece5f6", "#ad9fc6"],
    water: "#93d6ea",
    waterGlow: "#5ef0ff",
    sidewalk: "#f4eefb",
    curb: "#5fd6e6",
    markings: "#ff6fa8",
    unlit: "#b8acd3",
    offline: "#a9a4b3",
    trimOffline: "#bdb8c6",
  },
};

export const worldPalette = (theme: WorldTheme = "dark") => palettes[theme];
