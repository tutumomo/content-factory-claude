import React from "react";
import {Composition} from "remotion";
import {Episode, EpisodeProps} from "./Episode";

const defaults: EpisodeProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  accent: "#ffd166",
  channel: "",
  scenes: [
    {
      img: "",
      headline: "示範畫面",
      bullets: ["在這裡放重點", "時間軸由講稿配音長度決定"],
      frames: 90,
      kenBurns: "in",
    },
  ],
  captions: [{from: 10, to: 80, text: "這是字幕示範"}],
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Episode"
    component={Episode}
    durationInFrames={450}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={defaults}
    calculateMetadata={({props}) => {
      const frames = (props.scenes || []).reduce((n, s) => n + Math.max(1, s.frames || 1), 0) || 450;
      return {
        durationInFrames: frames,
        fps: props.fps || 30,
        width: props.width || 1080,
        height: props.height || 1920,
      };
    }}
  />
);
