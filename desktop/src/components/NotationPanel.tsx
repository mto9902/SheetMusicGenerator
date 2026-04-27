import { useLayoutEffect, useMemo, useRef, useState } from "react";

type Props = {
  svg: string;
  scale?: number;
};

function parseSvgSize(svg: string) {
  const tag = svg.match(/<svg[^>]*>/i)?.[0] ?? "";
  const width = Number(tag.match(/\bwidth="([\d.]+)(?:px)?"/i)?.[1]);
  const height = Number(tag.match(/\bheight="([\d.]+)(?:px)?"/i)?.[1]);

  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    return { width, height };
  }

  const viewBox = tag.match(/\bviewBox="[\d.\-]+\s+[\d.\-]+\s+([\d.]+)\s+([\d.]+)"/i);
  const viewBoxWidth = Number(viewBox?.[1]);
  const viewBoxHeight = Number(viewBox?.[2]);

  if (
    Number.isFinite(viewBoxWidth) &&
    Number.isFinite(viewBoxHeight) &&
    viewBoxWidth > 0 &&
    viewBoxHeight > 0
  ) {
    return { width: viewBoxWidth, height: viewBoxHeight };
  }

  return null;
}

export function NotationPanel({ svg, scale = 1 }: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [fitWidth, setFitWidth] = useState<number | null>(null);
  const svgSize = useMemo(() => parseSvgSize(svg), [svg]);
  const notationScale = Math.max(0.85, scale);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element || !svgSize) {
      setFitWidth(null);
      return;
    }

    function updateFitWidth() {
      if (!scrollRef.current || !svgSize) return;
      const styles = window.getComputedStyle(scrollRef.current);
      const horizontalPadding =
        Number.parseFloat(styles.paddingLeft) + Number.parseFloat(styles.paddingRight);
      const verticalPadding =
        Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom);
      const availableWidth = Math.max(0, scrollRef.current.clientWidth - horizontalPadding);
      const availableHeight = Math.max(0, scrollRef.current.clientHeight - verticalPadding);
      const aspectRatio = svgSize.width / svgSize.height;
      const widthThatFitsHeight = availableHeight > 0 ? availableHeight * aspectRatio : availableWidth;
      const width = Math.min(availableWidth, widthThatFitsHeight) * notationScale;

      setFitWidth(Math.max(280, Math.floor(width)));
    }

    updateFitWidth();
    const observer = new ResizeObserver(updateFitWidth);
    observer.observe(element);
    return () => observer.disconnect();
  }, [notationScale, svgSize]);

  if (!svg) {
    return (
      <div className="notation-frame notation-frame--empty">
        <p>Notation preview unavailable.</p>
      </div>
    );
  }

  return (
    <div className="notation-frame">
      <div className="notation-scroll" ref={scrollRef}>
        <div
          className="notation-artwork"
          style={{ width: fitWidth ? `${fitWidth}px` : `${notationScale * 100}%` }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}
