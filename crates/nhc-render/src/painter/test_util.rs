//! Cross-module Painter test fixture.
//!
//! Records every `Painter` call into a vector of `PainterCall`
//! variants. Used by `painter::tests` (trait-conformance) and by
//! per-family painter tests under `painter::material` /
//! `painter::families::*`.

#![cfg(test)]

use super::{
    FillRule, Paint, PathOps, Painter, Rect, Stroke, Transform, Vec2,
};

#[derive(Debug, PartialEq)]
pub enum PainterCall {
    FillRect(Rect, Paint),
    StrokeRect(Rect, Paint, Stroke),
    FillCircle(f32, f32, f32, Paint),
    FillEllipse(f32, f32, f32, f32, Paint),
    FillPolygon(Vec<Vec2>, Paint, FillRule),
    StrokePolyline(Vec<Vec2>, Paint, Stroke),
    FillPath(PathOps, Paint, FillRule),
    StrokePath(PathOps, Paint, Stroke),
    BeginGroup(f32),
    EndGroup,
    PushClip(PathOps, FillRule),
    PopClip,
    PushTransform(Transform),
    PopTransform,
}

#[derive(Debug, Default)]
pub struct MockPainter {
    pub calls: Vec<PainterCall>,
    pub group_depth: i32,
    pub clip_depth: i32,
    pub transform_depth: i32,
    pub max_group_depth: i32,
    pub max_clip_depth: i32,
    pub max_transform_depth: i32,
}

impl Painter for MockPainter {
    fn fill_rect(&mut self, rect: Rect, paint: &Paint) {
        self.calls.push(PainterCall::FillRect(rect, *paint));
    }
    fn stroke_rect(&mut self, rect: Rect, paint: &Paint, stroke: &Stroke) {
        self.calls.push(PainterCall::StrokeRect(rect, *paint, *stroke));
    }
    fn fill_circle(&mut self, cx: f32, cy: f32, r: f32, paint: &Paint) {
        self.calls.push(PainterCall::FillCircle(cx, cy, r, *paint));
    }
    fn fill_ellipse(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, paint: &Paint) {
        self.calls.push(PainterCall::FillEllipse(cx, cy, rx, ry, *paint));
    }
    fn fill_polygon(&mut self, vertices: &[Vec2], paint: &Paint, fill_rule: FillRule) {
        self.calls
            .push(PainterCall::FillPolygon(vertices.to_vec(), *paint, fill_rule));
    }
    fn stroke_polyline(&mut self, vertices: &[Vec2], paint: &Paint, stroke: &Stroke) {
        self.calls
            .push(PainterCall::StrokePolyline(vertices.to_vec(), *paint, *stroke));
    }
    fn fill_path(&mut self, path: &PathOps, paint: &Paint, fill_rule: FillRule) {
        self.calls
            .push(PainterCall::FillPath(path.clone(), *paint, fill_rule));
    }
    fn stroke_path(&mut self, path: &PathOps, paint: &Paint, stroke: &Stroke) {
        self.calls
            .push(PainterCall::StrokePath(path.clone(), *paint, *stroke));
    }
    fn begin_group(&mut self, opacity: f32) {
        self.group_depth += 1;
        if self.group_depth > self.max_group_depth {
            self.max_group_depth = self.group_depth;
        }
        self.calls.push(PainterCall::BeginGroup(opacity));
    }
    fn end_group(&mut self) {
        self.group_depth -= 1;
        self.calls.push(PainterCall::EndGroup);
    }
    fn push_clip(&mut self, path: &PathOps, fill_rule: FillRule) {
        self.clip_depth += 1;
        if self.clip_depth > self.max_clip_depth {
            self.max_clip_depth = self.clip_depth;
        }
        self.calls.push(PainterCall::PushClip(path.clone(), fill_rule));
    }
    fn pop_clip(&mut self) {
        self.clip_depth -= 1;
        self.calls.push(PainterCall::PopClip);
    }
    fn push_transform(&mut self, transform: Transform) {
        self.transform_depth += 1;
        if self.transform_depth > self.max_transform_depth {
            self.max_transform_depth = self.transform_depth;
        }
        self.calls.push(PainterCall::PushTransform(transform));
    }
    fn pop_transform(&mut self) {
        self.transform_depth -= 1;
        self.calls.push(PainterCall::PopTransform);
    }
}
