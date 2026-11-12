/** Animated wireframe globe / radar. Orbiting nodes = platform integrations. */
export default function Radar({ nodes }: { nodes: { key: string; label: string; up: boolean }[] }) {
  const C = 200;
  const R_ORBIT = 182;
  return (
    <div className="radar" aria-hidden>
      <svg viewBox="0 0 400 400">
        <defs>
          <linearGradient id="sweep" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#c8ff1e" stopOpacity="0" />
            <stop offset="1" stopColor="#c8ff1e" stopOpacity="0.32" />
          </linearGradient>
          <radialGradient id="core" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#c8ff1e" stopOpacity="0.18" />
            <stop offset="1" stopColor="#c8ff1e" stopOpacity="0" />
          </radialGradient>
        </defs>

        <circle cx={C} cy={C} r={150} fill="url(#core)" />
        <circle className="ring" cx={C} cy={C} r={196} />
        <circle className="ring lime" cx={C} cy={C} r={R_ORBIT} />
        <circle className="ring" cx={C} cy={C} r={150} />

        {/* globe: rotating meridians + static latitudes */}
        <g>
          <ellipse className="meridian" cx={C} cy={C} rx={150} ry={150} />
          <ellipse className="meridian" cx={C} cy={C} rx={150} ry={150} />
          <ellipse className="meridian" cx={C} cy={C} rx={150} ry={150} />
          <ellipse className="meridian" cx={C} cy={C} rx={150} ry={150} />
        </g>
        {[-100, -55, 0, 55, 100].map((dy) => {
          const rx = Math.sqrt(150 * 150 - dy * dy);
          return <ellipse key={dy} className="lat" cx={C} cy={C + dy} rx={rx} ry={rx * 0.12} />;
        })}

        {/* radar sweep */}
        <g className="sweep">
          <path d={`M${C} ${C} L${C + 150} ${C} A150 150 0 0 0 ${C + 150 * Math.cos(-0.7)} ${C + 150 * Math.sin(-0.7)} Z`} fill="url(#sweep)" />
          <line x1={C} y1={C} x2={C + 150} y2={C} stroke="#c8ff1e" strokeOpacity="0.7" />
        </g>

        {/* crosshair core */}
        <line x1={C - 14} y1={C} x2={C + 14} y2={C} stroke="#c8ff1e" />
        <line x1={C} y1={C - 14} x2={C} y2={C + 14} stroke="#c8ff1e" />
        <rect x={C - 4} y={C - 4} width={8} height={8} fill="#c8ff1e" />

        {/* tick marks */}
        {Array.from({ length: 72 }, (_, i) => {
          const a = (i / 72) * Math.PI * 2;
          const r1 = i % 6 === 0 ? 188 : 192;
          return (
            <line
              key={i}
              x1={C + r1 * Math.cos(a)}
              y1={C + r1 * Math.sin(a)}
              x2={C + 196 * Math.cos(a)}
              y2={C + 196 * Math.sin(a)}
              stroke={i % 6 === 0 ? "#c8ff1e" : "#3a4430"}
              strokeOpacity={i % 6 === 0 ? 0.6 : 1}
            />
          );
        })}

        {/* orbiting integration nodes */}
        <g className="orbit">
          {nodes.map((n, i) => {
            const a = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
            const x = C + R_ORBIT * Math.cos(a);
            const y = C + R_ORBIT * Math.sin(a);
            const color = n.up ? "#c8ff1e" : "#ff3d57";
            return (
              <g className="node" key={n.key}>
                <circle className="halo" cx={x} cy={y} r={5} stroke={color} style={{ animationDelay: `${i * 0.4}s` }} />
                <circle className="core" cx={x} cy={y} r={4.5} fill={color} />
                <text x={x + 9} y={y + 3}>
                  {n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
