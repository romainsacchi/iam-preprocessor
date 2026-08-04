Transport methodology
=====================

Energy-to-service conversion
----------------------------

For final energy in EJ/yr and specific consumption in MJ/service-km, the
application uses:

.. math::

   ES\;[\mathrm{billion\ km/yr}] =
   \frac{FE\;[\mathrm{EJ/yr}] \times 1000}
        {SEC\;[\mathrm{MJ/km}]}

This corrects the notebook's factor of :math:`10^6`, which overstated synthetic
services by a factor of 1,000. Passenger and freight units are assigned per row.

IMAGE battery-electric trucks
-----------------------------

IMAGE's medium/heavy truck electricity contains both plug-in hybrids and, in
later years, an additional component consistent with BEVs. For each region and
year, the application reconstructs PHEV electricity from the 10, 30, and 60 km
PHEV activity and intensity rows:

.. math::

   FE_{PHEV} = \sum_i ES_i \times SEC_{i,electricity} / 1000

It then derives:

.. math::

   FE_{BEV} = \max(FE_{truck,electricity} - FE_{PHEV}, 0)

.. math::

   ES_{BEV} = FE_{BEV} \times 1000 / SEC_{BEV}

The full-BEV SEC is not present in IMAGE and must therefore be supplied by the
user. World values are sums of regional results because IMAGE omits World PHEV
efficiency rows. Material negative residuals are recorded and clipped unless
strict mode is enabled.

Default assumptions
-------------------

The non-truck SEC values in ``default_sec.yaml`` are migrated verbatim from the
notebook. Their source was not recorded there. Override and document them before
using the results in published analyses.
