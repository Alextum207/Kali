

# Design Polish Plan

## What Changes

Comparing the reference screenshot to the current site, the design is already close but needs these refinements for a more editorial, polished feel:

### 1. Hero Section -- Vertical Text Positioning
Move the hero text block (names, date, tagline) higher on the page -- roughly the upper third -- instead of dead center. This creates a more cinematic composition where the couple in the photo gets more visual weight below.

### 2. Remove Rounded Corners from Images
The screenshot shows sharp-edged, editorial-style images with no border radius. Currently, the Our Story page uses `rounded-2xl` and `rounded-lg` on gallery images. These will be removed for a cleaner, magazine-style look.

### 3. Transparent Header on All Hero Pages
The Travel and Registry pages currently use a sticky solid header. They should use `<Header transparent />` since they both have full-bleed hero images, matching the homepage and Our Story page.

### 4. Lighter Event Details Background
The ceremony/reception section background should be a slightly cooler light gray rather than the warm cream, matching the screenshot's cleaner tone.

### 5. Consistent Section Spacing and Typography Weight
- Increase vertical padding on the event details section for more breathing room
- Ensure the "Ceremony" and "Reception" heading sizes match the screenshot's large, light serif style

### 6. Footer Refinement
Simplify footer styling with more subtle typography and tighter layout to match the minimal aesthetic.

---

## Technical Details

### Files Modified

**`src/pages/Index.tsx`**
- Shift hero text container from `items-center justify-center` to `items-end justify-center pb-[30vh]` or use `items-start pt-[18vh]` to position text in the upper third
- Change event details section from `bg-secondary` to a new lighter gray (`bg-[#f0efed]` or similar)
- Add more vertical padding (`py-32 md:py-44`)

**`src/pages/OurStory.tsx`**
- Remove `rounded-2xl` from story portrait image
- Remove `rounded-lg` from gallery images
- Adjust hero text positioning to upper-third

**`src/pages/Travel.tsx`**
- Switch `<Header />` to `<Header transparent />`
- Remove `rounded-lg` from lodging cards for sharp edges

**`src/pages/Registry.tsx`**
- Switch `<Header />` to `<Header transparent />`
- Soften the card overlay styling (reduce `rounded-2xl` to no rounding)

**`src/pages/RSVP.tsx`**
- Remove `rounded-sm` from form inputs for consistent sharp-edge aesthetic

**`src/index.css`**
- No changes needed; existing color variables are sufficient

