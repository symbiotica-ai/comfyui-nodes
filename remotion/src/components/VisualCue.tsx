// ABOUTME: Thin dispatcher that routes each cue type to its layout within CueContainer
// ABOUTME: Supports 12 cue types: icon, stat, label, list, progress, comparison, callout, counter, badge, quote, steps, chart

import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {
  VisualCue as VisualCueType,
  VisualCueTemplate,
} from "../types";
import { CueContainer, resolveBackground, resolveColorPlaceholders } from "./visual-cues/CueContainer";
import { CueIcon } from "./visual-cues/CueIcon";
import { CueTitle } from "./visual-cues/CueTitle";
import { StatValue } from "./visual-cues/StatValue";
import { ListItems } from "./visual-cues/ListItems";
import { ProgressBar } from "./visual-cues/ProgressBar";
import { ComparisonCard } from "./visual-cues/ComparisonCard";
import { CalloutCard } from "./visual-cues/CalloutCard";
import { CounterDisplay } from "./visual-cues/CounterDisplay";
import { BadgePill } from "./visual-cues/BadgePill";
import { QuoteBlock } from "./visual-cues/QuoteBlock";
import { StepsTimeline } from "./visual-cues/StepsTimeline";
import { ChartBar } from "./visual-cues/ChartBar";
import { ChartDonut } from "./visual-cues/ChartDonut";

interface Props {
  cue: VisualCueType;
  template: VisualCueTemplate;
  color: string;
}

export const VisualCue: React.FC<Props> = ({ cue, template, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const startFrame = Math.round(cue.startTime * fps);
  const localFrame = frame - startFrame;
  const cueScale = cue.scale ?? 1.0;
  const cardWidth = Math.round(template.cardWidth * cueScale);
  const valueSize = Math.round(template.valueSize * cueScale);
  const cueX = cue.x ?? (cue.position === "left" ? 8 : 92);
  const fontFamily = template.fontFamily || "Inter, system-ui, sans-serif";
  const textShadow = resolveColorPlaceholders(template.textShadow, color);

  // Staggered content reveal
  const contentDelay = template.entranceType === "slide-reveal" ? 3 : 0;
  const valueSpring = spring({
    frame: Math.max(0, localFrame - 5 - contentDelay),
    fps,
    config: template.entranceSpring,
  });
  const valueReveal = interpolate(valueSpring, [0, 1], [0, 1]);

  // Shared icon + title elements
  const icon = (
    <CueIcon
      name={cue.icon}
      color={color}
      localFrame={localFrame}
      template={template}
      cueScale={cueScale}
    />
  );

  const title = (
    <CueTitle
      title={cue.title}
      localFrame={localFrame}
      template={template}
      cueScale={cueScale}
      cardWidth={cardWidth}
      cueX={cueX}
      textShadow={textShadow}
    />
  );

  // --- Route by cue type ---

  switch (cue.type) {
    case "progress":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {title}
          <ProgressBar
            value={cue.value ?? "0"}
            title=""
            localFrame={localFrame}
            color={color}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "comparison":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {title}
          <ComparisonCard
            leftLabel={cue.leftLabel ?? "A"}
            leftValue={cue.leftValue ?? 0}
            rightLabel={cue.rightLabel ?? "B"}
            rightValue={cue.rightValue ?? 0}
            localFrame={localFrame}
            color={color}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "callout":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {title}
          <CalloutCard
            description={cue.description ?? ""}
            localFrame={localFrame}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "counter":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          <CounterDisplay
            value={cue.value ?? "0"}
            prefix={cue.prefix}
            suffix={cue.suffix}
            localFrame={localFrame}
            color={color}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
          {title}
        </CueContainer>
      );

    case "badge":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          <BadgePill
            title={cue.title}
            localFrame={localFrame}
            color={color}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "quote":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          <QuoteBlock
            text={cue.text ?? cue.title}
            attribution={cue.attribution}
            localFrame={localFrame}
            color={color}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "steps":
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {title}
          <StepsTimeline
            items={cue.items ?? []}
            activeStep={cue.activeStep}
            localFrame={localFrame}
            color={color}
            textShadow={textShadow}
            fontFamily={fontFamily}
          />
        </CueContainer>
      );

    case "chart": {
      const isDonut = cue.chartType === "donut";
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {title}
          {isDonut ? (
            <ChartDonut
              data={cue.data ?? []}
              title={cue.value ?? ""}
              localFrame={localFrame}
              color={color}
              textShadow={textShadow}
              fontFamily={fontFamily}
            />
          ) : (
            <ChartBar
              data={cue.data ?? []}
              localFrame={localFrame}
              color={color}
              textShadow={textShadow}
              fontFamily={fontFamily}
            />
          )}
        </CueContainer>
      );
    }

    // Original types: icon, stat, label, list
    default: {
      // Bar layout: inline stat + list footer
      if (template.layout === "bar") {
        const barFooter =
          cue.type === "list" && cue.items ? (
            <div
              style={{
                width: cardWidth,
                background: resolveBackground(template.background, color),
                borderTop: "1px solid rgba(255,255,255,0.1)",
                padding: `${Math.round(template.padding * cueScale) / 2}px ${Math.round(template.padding * cueScale)}px`,
                boxSizing: "border-box",
              }}
            >
              <ListItems
                items={cue.items}
                localFrame={localFrame}
                bulletColor={color}
                textShadow={textShadow}
                fontFamily={fontFamily}
              />
            </div>
          ) : undefined;

        return (
          <CueContainer cue={cue} template={template} color={color} barFooter={barFooter}>
            {icon}
            {cue.type === "stat" && cue.value && (
              <div style={{ opacity: valueReveal }}>
                <StatValue
                  value={cue.value}
                  localFrame={localFrame}
                  color={color}
                  fontSize={valueSize}
                  textShadow={textShadow}
                  fontFamily={fontFamily}
                />
              </div>
            )}
            {title}
          </CueContainer>
        );
      }

      // Card / text layout
      return (
        <CueContainer cue={cue} template={template} color={color}>
          {icon}
          {cue.type === "stat" && cue.value && (
            <div style={{ opacity: valueReveal }}>
              <StatValue
                value={cue.value}
                localFrame={localFrame}
                color={color}
                fontSize={valueSize}
                textShadow={textShadow}
                fontFamily={fontFamily}
              />
            </div>
          )}
          {title}
          {cue.type === "list" && cue.items && (
            <ListItems
              items={cue.items}
              localFrame={localFrame}
              bulletColor={color}
              textShadow={textShadow}
              fontFamily={fontFamily}
            />
          )}
        </CueContainer>
      );
    }
  }
};
