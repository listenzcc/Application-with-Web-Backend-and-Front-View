/*
 * File: contour.js
 * Author: Chuncheng Zhang
 * Date: 2026-09-11
 *
 * Purpose:
 *     等值线（marching squares）。FDS 房间图与 HYSPLIT 地图共用一份实现，
 *     两个页面都直接 <script src="/static/src/contour.js"> 引进来。
 *
 *     输入是一张规则标量网格，输出某个 level 的等值线。两条出口：
 *       contourSegments  逐格线段，画折线用
 *       contourRings     串成一条条折线，用来填充区域或转 GeoJSON
 *
 *     网格按行优先存：values[j * gw + i]，i 沿 x（列），j 沿 y（行）。
 *     角点位掩码：1=左上  2=右上  4=右下  8=左下。
 *
 *     阈值是「查看时」算的，跟网格一起放在前端，所以拖滑块改阈值不用重跑模拟。
 */

(function (global) {
    'use strict';

    /**
     * 在 a、b 之间线性插值出 level 的位置，返回 0~1 的比例。
     * 分母为 0（相邻两点同值）时取中点，否则会出 NaN 把整条线带歪。
     */
    function ratio(a, b, level) {
        const d = b - a;
        if (!isFinite(d) || d === 0) return 0.5;
        return Math.min(1, Math.max(0, (level - a) / d));
    }

    /**
     * 一个 level 的全部等值线段。
     * 返回扁平数组 [x1,y1,x2,y2, x1,y1,x2,y2, ...]，单位是网格下标。
     */
    function contourSegments(values, gw, gh, level) {
        const segs = [];
        if (!values || gw < 2 || gh < 2) return segs;

        const at = (i, j) => values[j * gw + i];

        for (let j = 0; j < gh - 1; j++) {
            for (let i = 0; i < gw - 1; i++) {
                const v0 = at(i, j);          // 左上
                const v1 = at(i + 1, j);      // 右上
                const v2 = at(i + 1, j + 1);  // 右下
                const v3 = at(i, j + 1);      // 左下

                let code = 0;
                if (v0 >= level) code |= 1;
                if (v1 >= level) code |= 2;
                if (v2 >= level) code |= 4;
                if (v3 >= level) code |= 8;
                // 四角同侧，这一格没有穿越
                if (code === 0 || code === 15) continue;

                // 四条边上的交点
                const top = [i + ratio(v0, v1, level), j];
                const right = [i + 1, j + ratio(v1, v2, level)];
                const bottom = [i + ratio(v3, v2, level), j + 1];
                const left = [i, j + ratio(v0, v3, level)];

                const push = (a, b) => segs.push(a[0], a[1], b[0], b[1]);

                switch (code) {
                    case 1: case 14: push(left, top); break;
                    case 2: case 13: push(top, right); break;
                    case 3: case 12: push(left, right); break;
                    case 4: case 11: push(right, bottom); break;
                    case 6: case 9: push(top, bottom); break;
                    case 7: case 8: push(left, bottom); break;
                    // 5 / 10 是鞍点：对角两个角在阈值同侧，连哪边要看格心
                    case 5: case 10: {
                        const centerHigh = (v0 + v1 + v2 + v3) / 4 >= level;
                        if (code === 5) {
                            if (centerHigh) { push(top, right); push(bottom, left); }
                            else { push(left, top); push(right, bottom); }
                        } else {
                            if (centerHigh) { push(left, top); push(right, bottom); }
                            else { push(top, right); push(bottom, left); }
                        }
                        break;
                    }
                }
            }
        }
        return segs;
    }

    /**
     * 把线段串成折线（环）。同一段共享边上的交点由两侧格内算出，
     * 输入值一样、公式一样，所以坐标逐位相同，直接按量化坐标做 key 连得起来。
     *
     * 注意：若折线自相交（鞍点处可能出现），串联是贪心的，可能连错分支。
     * 对烟羽这种单峰场不会碰到。
     */
    function contourRings(values, gw, gh, level) {
        const segs = contourSegments(values, gw, gh, level);
        const n = segs.length / 4;
        if (!n) return [];

        const key = (x, y) => Math.round(x * 1e4) + ',' + Math.round(y * 1e4);

        const at = new Map();
        for (let s = 0; s < n; s++) {
            const k1 = key(segs[s * 4], segs[s * 4 + 1]);
            const k2 = key(segs[s * 4 + 2], segs[s * 4 + 3]);
            if (!at.has(k1)) at.set(k1, []);
            if (!at.has(k2)) at.set(k2, []);
            at.get(k1).push(s);
            at.get(k2).push(s);
        }

        const used = new Uint8Array(n);
        const rings = [];

        /** 给定线段和它的一端 key，返回另一端的坐标。 */
        function farEnd(s, k) {
            const k1 = key(segs[s * 4], segs[s * 4 + 1]);
            return k1 === k
                ? [segs[s * 4 + 2], segs[s * 4 + 3]]
                : [segs[s * 4], segs[s * 4 + 1]];
        }

        for (let s0 = 0; s0 < n; s0++) {
            if (used[s0]) continue;
            used[s0] = 1;
            const ring = [
                [segs[s0 * 4], segs[s0 * 4 + 1]],
                [segs[s0 * 4 + 2], segs[s0 * 4 + 3]],
            ];

            // 头尾两端同时往外接，接不动为止
            for (const end of ['tail', 'head']) {
                let guard = 0;
                while (guard++ <= n) {
                    const pt = end === 'tail' ? ring[ring.length - 1] : ring[0];
                    const list = at.get(key(pt[0], pt[1])) || [];
                    let next = -1;
                    for (const s of list) {
                        if (!used[s]) { next = s; break; }
                    }
                    if (next < 0) break;
                    used[next] = 1;
                    const p = farEnd(next, key(pt[0], pt[1]));
                    if (end === 'tail') ring.push(p); else ring.unshift(p);
                }
            }

            // 首尾重合时去掉重复点，留在里面的闭合环更干净
            const a = ring[0];
            const b = ring[ring.length - 1];
            if (ring.length > 3 && Math.abs(a[0] - b[0]) < 1e-6
                && Math.abs(a[1] - b[1]) < 1e-6) {
                ring.pop();
            }
            if (ring.length >= 3) rings.push(ring);
        }
        return rings;
    }

    /**
     * Chaikin 切角细分，把折线磨圆。
     * 每切一次点翻倍，同时轮廓会稍微收一点点；画大图时一次就够。
     */
    function smoothRing(ring, passes) {
        let pts = ring;
        const n = Math.max(0, passes | 0);
        for (let k = 0; k < n; k++) {
            if (pts.length < 4) return pts;
            const out = [];
            for (let i = 0; i < pts.length; i++) {
                const p = pts[i];
                const q = pts[(i + 1) % pts.length];
                out.push([p[0] * 0.75 + q[0] * 0.25,
                          p[1] * 0.75 + q[1] * 0.25]);
                out.push([p[0] * 0.25 + q[0] * 0.75,
                          p[1] * 0.25 + q[1] * 0.75]);
            }
            pts = out;
        }
        return pts;
    }

    /** 网格全域的最小 / 最大值。用来判断阈值是不是低到「整片都在区内」。 */
    function gridExtent(values) {
        let lo = Infinity;
        let hi = -Infinity;
        for (let i = 0; i < values.length; i++) {
            const v = values[i];
            if (!isFinite(v)) continue;
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
        return [lo, hi];
    }

    /** 相邻点的最小间距，也就是原生网格步长。点太少推不出来就返回 fallback。 */
    function gridStep(sortedUnique, fallback) {
        let best = Infinity;
        for (let i = 1; i < sortedUnique.length; i++) {
            const d = sortedUnique[i] - sortedUnique[i - 1];
            if (d > 1e-9 && d < best) best = d;
        }
        return (isFinite(best) && best > 0)
            ? Number(best.toPrecision(3))
            : fallback;
    }

    /**
     * 3x3 均值平滑（1-2-1 权重），只统计 mask 为真的格点。
     *
     * 掩掉补边的格子，免得把外圈的低基数拉进来把边界值压塌。
     * 用途是把散点采样出的孤立高值格点连成片——不平滑的话，
     * 阈值一高等值线就画成一把碎点子。
     */
    function blurMasked(values, gw, gh, mask, passes) {
        let src = values;
        for (let k = 0; k < passes; k++) {
            const out = new Float32Array(src.length);
            for (let j = 0; j < gh; j++) {
                for (let i = 0; i < gw; i++) {
                    const idx = j * gw + i;
                    if (!mask[idx]) { out[idx] = src[idx]; continue; }
                    let sum = 0;
                    let weight = 0;
                    for (let dj = -1; dj <= 1; dj++) {
                        const jj = j + dj;
                        if (jj < 0 || jj >= gh) continue;
                        for (let di = -1; di <= 1; di++) {
                            const ii = i + di;
                            if (ii < 0 || ii >= gw) continue;
                            const n = jj * gw + ii;
                            if (!mask[n]) continue;
                            const w = (di === 0 && dj === 0) ? 4
                                : (di === 0 || dj === 0) ? 2 : 1;
                            sum += src[n] * w;
                            weight += w;
                        }
                    }
                    out[idx] = weight ? sum / weight : src[idx];
                }
            }
            src = out;
        }
        return src;
    }

    /**
     * 散点 -> 规则网格。
     *
     * 用在 HYSPLIT 那边：con2asc 输出的浓度点本来就落在等间距的经纬度格上，
     * 只是零值格点不输出，所以能靠最小间距把网格反推出来（默认 0.05°）。
     *
     * 数据外圈先铺一个明显低于任何观测值的基数，再逐层往里递减，
     * 这样阈值略高于本帧最低值时等值线也能在画面内收口，
     * 不会沿着数据边界走出一条生硬的锯齿。
     *
     * points: [{lon, lat, value}]
     * opts:   pad     往外补几格
     *         step    推不出网格间距时的默认步长
     *         smooth  平滑几遍（0 = 不平滑）
     *
     * 返回 {values, mask, gw, gh, dlon, dlat, lon0, lat0, lo, hi}，
     * values 按行优先存，格子 (i, j) 的经纬度是
     * lon0 + i * dlon、lat0 + j * dlat。
     */
    function gridFromPoints(points, opts) {
        opts = opts || {};
        const pad = Math.max(0, (opts.pad === undefined ? 5 : opts.pad) | 0);
        const fallbackStep = opts.step > 0 ? opts.step : 0.05;
        const smooth = Math.max(0, (opts.smooth || 0) | 0);

        const lons = [];
        const lats = [];
        const seenLon = new Set();
        const seenLat = new Set();
        for (const p of points) {
            if (!seenLon.has(p.lon)) { seenLon.add(p.lon); lons.push(p.lon); }
            if (!seenLat.has(p.lat)) { seenLat.add(p.lat); lats.push(p.lat); }
        }
        lons.sort((a, b) => a - b);
        lats.sort((a, b) => a - b);

        const dlon = gridStep(lons, fallbackStep);
        const dlat = gridStep(lats, fallbackStep);

        const i0 = Math.round(lons[0] / dlon) - pad;
        const i1 = Math.round(lons[lons.length - 1] / dlon) + pad;
        const j0 = Math.round(lats[0] / dlat) - pad;
        const j1 = Math.round(lats[lats.length - 1] / dlat) + pad;

        const gw = Math.max(2, i1 - i0 + 1);
        const gh = Math.max(2, j1 - j0 + 1);

        let lo = Infinity;
        let hi = -Infinity;
        for (const p of points) {
            if (p.value < lo) lo = p.value;
            if (p.value > hi) hi = p.value;
        }
        if (!isFinite(lo)) { lo = 0; hi = 1; }
        const rng = Math.max(hi - lo, 1e-3);
        const outside = lo - rng;

        let values = new Float32Array(gw * gh).fill(outside);
        const mask = new Uint8Array(gw * gh);
        for (const p of points) {
            const i = Math.round(p.lon / dlon) - i0;
            const j = Math.round(p.lat / dlat) - j0;
            if (i < 0 || i >= gw || j < 0 || j >= gh) continue;
            values[j * gw + i] = p.value;
            mask[j * gw + i] = 1;
        }

        if (smooth > 0) values = blurMasked(values, gw, gh, mask, smooth);

        // 从数据区一层层往外渗，每层低一个 step，最多渗 pad + 10 层。
        //
        // step 必须让 pad 层之内就掉到 lo 以下：否则边界上那些高值格点
        // 一路渗下去仍在阈值之上，等值线会一直顶到补边的外框被裁断。
        // 取 1.5 倍留点余量。
        const step = Math.max(rng / Math.max(pad, 1) * 1.5, rng * 0.05);
        let frontier = [];
        for (let k = 0; k < values.length; k++) {
            if (mask[k]) frontier.push(k);
        }
        const spread = (idx, n) => {
            if (values[n] > outside) return false;
            values[n] = values[idx] - step;
            return true;
        };
        for (let pass = 0; pass < pad + 10 && frontier.length; pass++) {
            const next = [];
            for (const idx of frontier) {
                const i = idx % gw;
                const j = (idx - i) / gw;
                if (i > 0 && spread(idx, idx - 1)) next.push(idx - 1);
                if (i < gw - 1 && spread(idx, idx + 1)) next.push(idx + 1);
                if (j > 0 && spread(idx, idx - gw)) next.push(idx - gw);
                if (j < gh - 1 && spread(idx, idx + gw)) next.push(idx + gw);
            }
            frontier = next;
        }

        return {
            values, mask, gw, gh, dlon, dlat,
            lon0: i0 * dlon, lat0: j0 * dlat,
            lo, hi,
        };
    }

    global.Contour = {
        segments: contourSegments,
        rings: contourRings,
        smoothRing: smoothRing,
        extent: gridExtent,
        blurMasked: blurMasked,
        gridFromPoints: gridFromPoints,
        gridStep: gridStep,
    };
})(typeof window !== 'undefined' ? window : globalThis);
