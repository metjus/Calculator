import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MapPin } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { AreaSuggestion } from "../lib/api";
import { useTheme } from "../lib/theme";
import { Banner } from "./ui";

const ACCENT = { light: "#0b6e72", dark: "#4fb8b3" }; // --accent in tokens.css

type Props = {
  tileUrl: string;
  attribution: string;
  source: "osm" | "mapy";
  area: AreaSuggestion | null;
  mode: "radius" | "region";
  radiusKm: number;
};

/** Mapy.com's terms ask for its logo on the map. */
const MapyLogo = L.Control.extend({
  options: { position: "bottomleft" },
  onAdd() {
    const link = L.DomUtil.create("a", "map-logo");
    link.href = "https://mapy.com/";
    link.target = "_blank";
    link.rel = "noopener";
    link.innerHTML = '<img src="https://api.mapy.com/img/api/logo.svg" alt="Mapy.com" />';
    L.DomEvent.disableClickPropagation(link);
    return link;
  },
});

/** Why a tile failed: the API answers a failed tile with JSON saying what the tile server did. */
async function tileProblem(src: string): Promise<string> {
  try {
    const response = await fetch(src);
    const body = (await response.json()) as { detail?: string };
    return body.detail ?? `the map server answered ${response.status}`;
  } catch {
    return "the map server could not be reached";
  }
}

/** Read-only preview of the search area: a circle for a radius search, the bounding box for a whole region. */
export function MapPreview({ tileUrl, attribution, source, area, mode, radiusKm }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const { theme } = useTheme();
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!box.current || !area) return;
    const instance = L.map(box.current, { zoomControl: true, scrollWheelZoom: false, attributionControl: true }).setView([area.lat, area.lon], 11);
    // Tiles come through our API (/api/search/tiles), which fetches them from OSM or Mapy.com.
    const tiles = L.tileLayer(tileUrl, { maxZoom: 18, attribution }).addTo(instance);
    let loaded = false;
    let asked = false;
    tiles.on("tileload", () => {
      loaded = true;
      setProblem(null);
    });
    tiles.on("tileerror", (event) => {
      if (loaded || asked) return; // one missing tile among good ones is not worth a message
      asked = true;
      void tileProblem((event.tile as HTMLImageElement).src).then((text) => {
        if (!loaded) setProblem(text);
      });
    });
    if (source === "mapy") new MapyLogo().addTo(instance);
    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
      layer.current = null;
      setProblem(null);
    };
    // Created when the container appears; area changes are drawn by the effect below.
  }, [tileUrl, attribution, source, Boolean(area)]);

  useEffect(() => {
    const instance = map.current;
    const group = layer.current;
    if (!instance || !group || !area) return;
    group.clearLayers();
    // Leaflet needs literal colours; child effects run before ThemeProvider updates <html>, so don't read the CSS var.
    const accent = ACCENT[theme];
    const style = { color: accent, weight: 2, fillColor: accent, fillOpacity: 0.12 };
    L.circleMarker([area.lat, area.lon], { radius: 5, color: accent, weight: 2, fillColor: accent, fillOpacity: 1 }).addTo(group);
    if (mode === "region" && area.bbox) {
      const [minLon, minLat, maxLon, maxLat] = area.bbox;
      const bounds = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
      L.rectangle(bounds, { ...style, dashArray: "6 6" }).addTo(group);
      instance.fitBounds(bounds, { padding: [16, 16] });
    } else {
      L.circle([area.lat, area.lon], { ...style, radius: radiusKm * 1000 }).addTo(group);
      // Circle.getBounds() needs a rendered layer; derive the box from the centre instead.
      instance.fitBounds(L.latLng(area.lat, area.lon).toBounds(radiusKm * 2000), { padding: [16, 16] });
    }
  }, [area, mode, radiusKm, theme]);

  if (!area) {
    return (
      <div className="map map-empty">
        <MapPin size={22} aria-hidden />
        <span>Pick a country and a town to see the search area.</span>
      </div>
    );
  }
  return (
    <>
      <div
        className="map"
        ref={box}
        role="img"
        aria-label={mode === "region" ? `Map of ${area.label}` : `Map: ${radiusKm} km around ${area.label}`}
      />
      {problem && (
        <Banner kind="warn">
          The map could not be loaded: {problem}.{" "}
          {source === "mapy" ? (
            <>
              Check the Mapy.com key in <Link to="/settings">Settings</Link>.
            </>
          ) : (
            <>
              A free Mapy.com key in <Link to="/settings">Settings</Link> shows the map from Mapy.com instead.
            </>
          )}{" "}
          Searching works without the map.
        </Banner>
      )}
    </>
  );
}
