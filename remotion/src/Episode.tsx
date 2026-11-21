import React from "react";
import {AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export type Scene = {
  img: string;
  headline: string;
  bullets: string[];
  frames: number;
  kenBurns?: "in" | "out";
};

export type Caption = {from: number; to: number; text: string};

export type EpisodeProps = {
  width: number;
  height: number;
  fps: number;
  accent?: string;
  channel?: string;
  scenes: Scene[];
  captions: Caption[];
};

const ease = (t: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);

const SceneLayer: React.FC<{scene: Scene; index: number; accent: string; vertical: boolean}> = ({
  scene,
  index,
  accent,
  vertical,
}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const n = Math.max(1, scene.frames);
  const out = scene.kenBurns === "out";
  const zoom = interpolate(frame, [0, n], out ? [1.12, 1.02] : [1.02, 1.12], {extrapolateRight: "clamp"});
  const drift = interpolate(frame, [0, n], out ? [1.5, -1.5] : [-1.5, 1.5], {extrapolateRight: "clamp"});
  const enter = ease(frame / Math.max(6, fps * 0.35));
  const leave = interpolate(frame, [n - Math.round(fps * 0.3), n], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = Math.min(enter, leave);
  const head = spring({frame: frame - Math.round(fps * 0.15), fps, config: {damping: 200}});
  const pad = Math.round(width * (vertical ? 0.075 : 0.06));

  return (
    <AbsoluteFill style={{opacity, backgroundColor: "#0b0d12"}}>
      <AbsoluteFill style={{transform: `scale(${zoom}) translateX(${drift}%)`}}>
        <Img src={staticFile(scene.img)} style={{width: "100%", height: "100%", objectFit: "cover"}} />
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          background: vertical
            ? "linear-gradient(180deg, rgba(6,8,12,0.82) 0%, rgba(6,8,12,0.25) 38%, rgba(6,8,12,0.15) 55%, rgba(6,8,12,0.88) 100%)"
            : "linear-gradient(90deg, rgba(6,8,12,0.88) 0%, rgba(6,8,12,0.55) 42%, rgba(6,8,12,0.05) 72%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: pad,
          right: pad,
          top: vertical ? "11%" : "14%",
          maxWidth: vertical ? "100%" : "62%",
          transform: `translateY(${(1 - head) * 36}px)`,
          opacity: head,
        }}
      >
        <div
          style={{
            display: "inline-block",
            padding: "6px 14px",
            marginBottom: 18,
            borderRadius: 999,
            background: accent,
            color: "#0b0d12",
            fontSize: Math.round(width * 0.024),
            fontWeight: 800,
            letterSpacing: 1,
          }}
        >
          {String(index + 1).padStart(2, "0")}
        </div>
        <div
          style={{
            color: "#ffffff",
            fontSize: Math.round(width * (vertical ? 0.082 : 0.058)),
            fontWeight: 900,
            lineHeight: 1.16,
            letterSpacing: -0.5,
            textShadow: "0 4px 24px rgba(0,0,0,0.55)",
            whiteSpace: "pre-wrap",
          }}
        >
          {scene.headline}
        </div>
        <div style={{marginTop: Math.round(width * 0.03)}}>
          {scene.bullets.map((b, i) => {
            const t = spring({
              frame: frame - Math.round(fps * (0.45 + i * 0.18)),
              fps,
              config: {damping: 200},
            });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: Math.round(width * 0.014),
                  marginBottom: Math.round(width * 0.012),
                  opacity: t,
                  transform: `translateX(${(1 - t) * -28}px)`,
                }}
              >
                <div
                  style={{
                    width: Math.round(width * 0.012),
                    height: Math.round(width * 0.012),
                    marginTop: Math.round(width * 0.013),
                    borderRadius: 3,
                    background: accent,
                    flex: "0 0 auto",
                  }}
                />
                <div
                  style={{
                    color: "rgba(255,255,255,0.93)",
                    fontSize: Math.round(width * (vertical ? 0.042 : 0.03)),
                    fontWeight: 600,
                    lineHeight: 1.35,
                    textShadow: "0 2px 12px rgba(0,0,0,0.6)",
                  }}
                >
                  {b}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Captions: React.FC<{captions: Caption[]}> = ({captions}) => {
  const frame = useCurrentFrame();
  const {width, height, fps} = useVideoConfig();
  const vertical = height > width;
  const active = captions.find((c) => frame >= c.from && frame < c.to);
  if (!active) return null;
  const local = frame - active.from;
  const dur = Math.max(1, active.to - active.from);
  const a = interpolate(local, [0, 4, dur - 4, dur], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rise = interpolate(local, [0, 6], [10, 0], {extrapolateRight: "clamp"});
  return (
    <div
      style={{
        position: "absolute",
        left: "8%",
        right: "8%",
        bottom: vertical ? "15%" : "9%",
        display: "flex",
        justifyContent: "center",
        opacity: a,
        transform: `translateY(${rise}px)`,
      }}
    >
      <div
        style={{
          padding: `${Math.round(width * 0.012)}px ${Math.round(width * 0.028)}px`,
          borderRadius: Math.round(width * 0.012),
          background: "rgba(8,10,14,0.72)",
          color: "#fff",
          fontSize: Math.round(width * (vertical ? 0.052 : 0.036)),
          fontWeight: 700,
          lineHeight: 1.35,
          textAlign: "center",
          maxWidth: vertical ? "100%" : "78%",
          textShadow: "0 2px 10px rgba(0,0,0,0.6)",
          WebkitTextStroke: `${Math.max(1, Math.round(width * 0.0012))}px rgba(0,0,0,0.35)`,
        }}
      >
        {active.text}
      </div>
    </div>
  );
};

export const Episode: React.FC<EpisodeProps> = ({scenes, captions, accent = "#ffd166", channel = "", width}) => {
  const {height, fps} = useVideoConfig();
  const vertical = height > width;
  let from = 0;
  const placed = scenes.map((s) => {
    const at = from;
    from += Math.max(1, s.frames);
    return {...s, at};
  });
  const last = Math.max(1, from);
  const bar = interpolate(useCurrentFrame(), [0, last], [0, 1], {extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{backgroundColor: "#0b0d12"}}>
      {placed.map((s, i) => (
        <Sequence key={i} from={s.at} durationInFrames={Math.max(1, s.frames)}>
          <SceneLayer scene={s} index={i} accent={accent} vertical={vertical} />
        </Sequence>
      ))}
      <Captions captions={captions} />
      <div style={{position: "absolute", left: 0, right: 0, bottom: 0, height: 6, background: "rgba(255,255,255,0.12)"}}>
        <div style={{width: `${bar * 100}%`, height: "100%", background: accent}} />
      </div>
      {channel ? (
        <div
          style={{
            position: "absolute",
            top: Math.round(width * 0.035),
            right: Math.round(width * 0.045),
            color: "rgba(255,255,255,0.75)",
            fontSize: Math.round(width * 0.022),
            fontWeight: 700,
            letterSpacing: 1,
            textShadow: "0 2px 8px rgba(0,0,0,0.6)",
          }}
        >
          {channel}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
