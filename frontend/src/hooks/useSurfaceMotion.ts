import { useEffect } from "react";
import { useMotionPreferences } from "./useMotionPreferences";

const clamp = (n: number, low = 0, high = 1) =>
  Math.min(high, Math.max(low, n));
export function useSurfaceMotion() {
  const { reduced, pointer } = useMotionPreferences();
  useEffect(() => {
    const root = document.documentElement;
    let frame = 0;
    let pointerFrame = 0;
    let target: HTMLElement | null = null;
    let pointerEvent: PointerEvent | null = null;
    const observed = new Set<Element>();
    const selector =
      ".summary-costs > div, .summary-money > span, .numbers > div, .journey-kicker, .card-step, .decision-caption";
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("motion-row-visible");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    const discover = () => {
      for (const el of observed) {
        if (!el.isConnected) {
          observer.unobserve(el);
          observed.delete(el);
        }
      }
      document.querySelectorAll(selector).forEach((el) => {
        if (!observed.has(el)) {
          observed.add(el);
          observer.observe(el);
        }
      });
      schedule();
    };
    const update = () => {
      frame = 0;
      const max = Math.max(1, root.scrollHeight - window.innerHeight);
      const progress = clamp(window.scrollY / max);
      document
        .querySelector<HTMLElement>(".calm-header")
        ?.style.setProperty("--scroll-progress", `${progress}`);
      document
        .querySelector<HTMLElement>(".background-grid")
        ?.style.setProperty(
          "--grid-shift",
          reduced ? "0px" : `${progress * 8}px`,
        );
      const stack = document.querySelector<HTMLElement>(".flashcard-stack");
      if (!stack) return;
      const cards = [...stack.querySelectorAll<HTMLElement>(".journey-card")];
      const top = stack.getBoundingClientRect().top;
      const gap = parseFloat(getComputedStyle(stack).gap) || 0;
      const stackBottom =
        top +
        stack.offsetHeight -
        (parseFloat(getComputedStyle(stack).paddingBottom) || 0);
      const heights = cards.map((c) => c.offsetHeight);
      const sticky = cards.map((c) => parseFloat(getComputedStyle(c).top) || 0);
      let offset = 0;
      const positions = cards.map((c, i) => {
        const position = Math.min(
          stackBottom - heights[i],
          Math.max(top + offset, sticky[i]),
        );
        offset += heights[i] + gap;
        return position;
      });
      cards.forEach((c, i) => {
        const enabled =
          !reduced &&
          getComputedStyle(c).position === "sticky" &&
          i < cards.length - 1;
        const overlap = enabled
          ? clamp(
              (positions[i] + heights[i] - positions[i + 1]) /
                Math.max(1, heights[i] - (sticky[i + 1] - sticky[i])),
            )
          : 0;
        c.style.setProperty("--cover-scale", `${1 - overlap * 0.04}`);
        c.style.setProperty("--cover-y", `${-overlap * 12}px`);
        c.style.setProperty("--cover-brightness", `${1 - overlap * 0.12}`);
        c.style.setProperty("--cover-blur", `${overlap * 1.5}px`);
        c.style.setProperty("--label-opacity", `${1 - overlap * 0.2}`);
        c.dataset.covered = overlap > 0 ? "true" : "false";
      });
    };
    function schedule() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    const resetTarget = () => {
      if (!target) return;
      target.style.setProperty("--hover-x", "0px");
      target.style.setProperty("--hover-y", "0px");
      target.style.setProperty("--tilt-x", "0deg");
      target.style.setProperty("--tilt-y", "0deg");
      target.removeAttribute("data-pointer-active");
      target = null;
    };
    const paintPointer = () => {
      pointerFrame = 0;
      if (!target || !pointerEvent) return;
      const r = target.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const x = clamp((pointerEvent.clientX - r.left) / r.width, 0, 1) * 2 - 1;
      const y = clamp((pointerEvent.clientY - r.top) / r.height, 0, 1) * 2 - 1;
      if (target.matches("button")) {
        const dx = x * 6,
          dy = y * 6;
        const limit = Math.max(1, Math.hypot(dx, dy) / 6);
        target.style.setProperty("--hover-x", `${dx / limit}px`);
        target.style.setProperty("--hover-y", `${dy / limit}px`);
      } else {
        const limit = Math.max(1, Math.hypot(x, y));
        target.style.setProperty("--tilt-x", `${(-y * 3) / limit}deg`);
        target.style.setProperty("--tilt-y", `${(x * 3) / limit}deg`);
        target.style.setProperty(
          "--sheen-x",
          `${((x + 1) * r.width) / 2 - 25}px`,
        );
      }
    };
    const move = (event: PointerEvent) => {
      if (reduced || !pointer || event.pointerType === "touch") return;
      const el = event.target instanceof Element ? event.target : null;
      const next =
        el?.closest<HTMLElement>(
          "button:not(:disabled), .journey-card, .trip-summary, .other-decision, .graph-panel",
        ) || null;
      if (next !== target) {
        resetTarget();
        target = next;
      }
      pointerEvent = event;
      if (target) {
        target.setAttribute("data-pointer-active", "true");
        if (!pointerFrame) pointerFrame = requestAnimationFrame(paintPointer);
      }
    };
    const leave = () => resetTarget();
    const out = (event: PointerEvent) => {
      if (!event.relatedTarget) leave();
    };
    const visibility = () => {
      root.dataset.tabActive = document.hidden ? "false" : "true";
      if (document.hidden) resetTarget();
    };
    const mutations = new MutationObserver(discover);
    mutations.observe(document.getElementById("root") || document.body, {
      childList: true,
      subtree: true,
    });
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    document.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerout", out, { passive: true });
    document.addEventListener("visibilitychange", visibility);
    visibility();
    discover();
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(pointerFrame);
      observer.disconnect();
      mutations.disconnect();
      resetTarget();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("pointermove", move);
      document.removeEventListener("visibilitychange", visibility);
      document.removeEventListener("pointerout", out);
    };
  }, [reduced, pointer]);
  return { reduced };
}
